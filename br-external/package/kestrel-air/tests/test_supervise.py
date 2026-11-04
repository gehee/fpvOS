#!/usr/bin/env python3
"""Exercise real processes, signals, orphan cleanup and bounded restart/logging."""
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
                        '-DRETRY_MS=80', '-DSTABLE_MS=1000', '-DSTOP_MS=200',
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

    def test_crash_loop_stops_after_five_attempts(self):
        self.start('fail')
        self.process.wait(timeout=5)
        self.assertEqual(self.process.returncode, 1)
        self.assertEqual(self.attempts(), 5)
        self.assertTrue(self.read('status').startswith('failed '))
        self.assertIn('exit code=17', self.read('current.log'))

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

    def test_missing_launcher_is_bounded_and_reported(self):
        self.process = subprocess.Popen([str(self.binary), str(self.root), '/no/such/launcher'])
        self.process.wait(timeout=5)
        self.assertEqual(self.process.returncode, 1)
        self.assertIn('failures=5', self.read('status'))
        self.assertIn('exit code=127', self.read('current.log'))


if __name__ == '__main__':
    unittest.main()
