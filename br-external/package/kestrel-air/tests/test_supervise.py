#!/usr/bin/env python3
"""Exercise real processes, signals, orphan cleanup, unbounded restart and bounded logging."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

PACKAGE = Path(__file__).resolve().parents[1]

WORKER = r'''
import fcntl, os, signal, sys, time
from pathlib import Path
mode = sys.argv[1]
lock = open('camera.lock', 'w')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
attempts = Path('attempts')
n = int(attempts.read_text()) + 1 if attempts.exists() else 1
attempts.write_text(str(n))
with open('starts', 'a') as f: f.write(f'{time.monotonic()}\n')
Path('worker').write_text(str(os.getpid()))
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
if mode == 'fail':
    sys.exit(17)
if mode == 'reset':
    if n == 4:
        time.sleep(1.3)
    if n < 9:
        sys.exit(17)
if mode in ('orphan', 'stubborn'):
    child = os.fork()
    if not child:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        Path('helper').write_text(str(os.getpid()))
        while True: time.sleep(.05)
    if mode == 'stubborn': signal.signal(signal.SIGTERM, signal.SIG_IGN)
while True:
    if mode == 'noisy': os.write(1, b'X' * 8192)
    else: time.sleep(.02)
'''


class Supervision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name)/'supervise'
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2',
                        '-DRETRY_MS=80', '-DMAX_RETRY_MS=200', '-DSTABLE_MS=1000', '-DSTOP_MS=200',
                        '-DLOG_BYTES=4096', str(PACKAGE/'supervise.c'), '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.worker = self.root/'worker.py'
        self.worker.write_text(WORKER)
        self.process = None
        self.addCleanup(self.stop)

    def start(self, mode):
        self.command = [str(self.binary), str(self.root), sys.executable, str(self.worker), mode]
        self.process = subprocess.Popen(self.command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)

    def wait_for(self, predicate, timeout=5):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.02)
        self.fail('timed out: '+self.read('status'))

    def read(self, file):
        try: return (self.root/file).read_text()
        except FileNotFoundError: return ''

    def attempts(self):
        return int(self.read('attempts') or 0)

    def test_stop_is_graceful_and_does_not_restart(self):
        self.start('steady')
        self.wait_for(lambda: self.attempts() == 1)
        pid = int(self.read('worker'))
        self.stop()
        self.assertEqual(self.process.returncode, 0)
        self.assertEqual(self.attempts(), 1)
        self.assertTrue(self.read('status').startswith('stopped'))
        self.assertFalse(Path(f'/proc/{pid}').exists())
        self.assertFalse((self.root/'pid').exists())
        self.assertIn('exit code=0 signal=0', self.read('current.log'))

    def test_duplicate_supervisor_does_not_disturb_owner(self):
        self.start('steady')
        self.wait_for(lambda: self.attempts() == 1)
        result = subprocess.run(self.command, capture_output=True, timeout=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(int(self.read('pid')), self.process.pid)
        self.assertEqual(self.attempts(), 1)

    def test_crash_loop_keeps_retrying_with_capped_backoff(self):
        self.start('fail')
        self.wait_for(lambda: self.attempts() >= 8)
        self.assertIsNone(self.process.poll())
        self.assertIn('exit code=17', self.read('current.log'))
        starts = [float(x) for x in self.read('starts').split()]
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        # Waits of 80, 160, then 200 ms (the cap); each gap also holds the
        # child's own start-up, so compare the gaps with the first one.
        self.assertGreater(gaps[1] - gaps[0], .04)
        capped = [gap - gaps[0] for gap in gaps[2:7]]
        self.assertGreater(min(capped), .06)
        self.assertLess(max(capped), .25)
        self.assertLess(max(capped) - min(capped), .08)
        self.stop()
        self.assertEqual(self.process.returncode, 0)
        self.assertTrue(self.read('status').startswith('stopped'))

    def test_stable_run_resets_failure_budget(self):
        self.start('reset')
        self.wait_for(lambda: self.attempts() == 9)
        self.assertIsNone(self.process.poll())

    def test_crash_cleans_orphans_and_releases_camera_lock(self):
        self.start('orphan')
        self.wait_for(lambda: bool(self.read('helper')))
        old_worker, old_helper = int(self.read('worker')), int(self.read('helper'))
        os.kill(old_worker, signal.SIGKILL)
        self.wait_for(lambda: self.attempts() >= 2)
        self.assertFalse(Path(f'/proc/{old_worker}').exists())
        self.assertFalse(Path(f'/proc/{old_helper}').exists())
        self.assertIn('signal=9', self.read('current.log'))

    def test_stubborn_group_is_killed_and_reaped_on_stop(self):
        self.start('stubborn')
        self.wait_for(lambda: bool(self.read('helper')))
        pids = [int(self.read(x)) for x in ('worker', 'helper')]
        self.stop()
        for pid in pids:
            self.assertFalse(Path(f'/proc/{pid}').exists())
        self.assertEqual(self.attempts(), 1)

    def test_logs_are_bounded_and_flood_cannot_block_stop(self):
        self.start('noisy')
        self.wait_for(lambda: (self.root/'previous.log').exists())
        self.stop()
        for name in ('current.log', 'previous.log'):
            self.assertLessEqual((self.root/name).stat().st_size, 4096)
        self.assertTrue(self.read('status').startswith('stopped'))

    def test_missing_launcher_is_retried_and_reported(self):
        self.process = subprocess.Popen([str(self.binary), str(self.root), '/no/such/launcher'],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.wait_for(lambda: 'failures=6' in self.read('status'))
        self.assertIsNone(self.process.poll())
        self.assertIn('exit code=127', self.read('current.log'))

    def test_stop_right_after_start_does_not_wait_for_kill(self):
        # A stop that races the fork must end the child at once, not after
        # the TERM-then-KILL timeouts (2 x STOP_MS).
        # The pid file is written once the handlers are in place, just before
        # the first fork.
        for delay in (0, .0005, .001, .002, .005):
            (self.root/'pid').unlink(missing_ok=True)
            self.start('steady')
            self.wait_for(lambda: (self.root/'pid').exists())
            time.sleep(delay)
            began = time.monotonic()
            self.process.terminate()
            self.process.wait(timeout=5)
            self.assertLess(time.monotonic() - began, .19, f'delay {delay}')
            self.assertEqual(self.process.returncode, 0)


if __name__ == '__main__':
    unittest.main()
