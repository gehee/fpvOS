#!/usr/bin/env python3
"""Exercise real processes, signals, orphan cleanup, unbounded restart and bounded logging,
and that log, status, pipe and fork failures never stop the application."""
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

# Preloaded into the supervisor only (it unsets LD_PRELOAD before any exec):
# while a marker file exists in the state directory, fork() or pipe2() fails,
# or a write() to a regular file reports a full filesystem.
FAULTS = r'''
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

__attribute__((constructor)) static void faults_init(void) { unsetenv("LD_PRELOAD"); }

static int armed(const char *marker) { return access(marker, F_OK) == 0; }

pid_t fork(void)
{
    static pid_t (*real)(void);
    if (!real) real = (pid_t (*)(void))dlsym(RTLD_NEXT, "fork");
    if (armed("fail-fork")) { errno = EAGAIN; return -1; }
    return real();
}

int pipe2(int fds[2], int flags)
{
    static int (*real)(int[2], int);
    if (!real) real = (int (*)(int[2], int))dlsym(RTLD_NEXT, "pipe2");
    if (armed("fail-pipe")) { errno = EMFILE; return -1; }
    return real(fds, flags);
}

ssize_t write(int fd, const void *buf, size_t n)
{
    static ssize_t (*real)(int, const void *, size_t);
    if (!real) real = (ssize_t (*)(int, const void *, size_t))dlsym(RTLD_NEXT, "write");
    struct stat st;
    if (fd > 2 && armed("fail-write") && !fstat(fd, &st) && S_ISREG(st.st_mode)) {
        errno = ENOSPC;
        return -1;
    }
    return real(fd, buf, n);
}
'''


class Supervision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name)/'supervise'
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2',
                        '-DRETRY_MS=80', '-DMAX_RETRY_MS=200', '-DSTABLE_MS=1000', '-DSTOP_MS=200',
                        '-DLOG_BYTES=4096', '-DLOG_RETRY_MS=100',
                        str(PACKAGE.parent/'kestrel-common/supervise.c'), '-o', str(cls.binary)], check=True)
        source = Path(cls.build.name)/'faults.c'
        source.write_text(FAULTS)
        cls.faults = Path(cls.build.name)/'faults.so'
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', '-shared', '-fPIC',
                        str(source), '-o', str(cls.faults), '-ldl'], check=True)

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

    def start(self, mode, faults=False):
        self.command = [str(self.binary), str(self.root), sys.executable, str(self.worker), mode]
        env = {**os.environ, 'LD_PRELOAD': str(self.faults)} if faults else None
        self.process = subprocess.Popen(self.command, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, env=env)

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

    def test_unwritable_state_directory_keeps_the_app_and_its_restarts(self):
        # A /run that takes no new files (here: no write permission; on a unit:
        # ENOSPC) costs status updates and log rotation, never the application.
        if os.geteuid() == 0:
            self.skipTest('root ignores directory permissions')
        self.start('steady')
        self.wait_for(lambda: self.attempts() == 1 and self.read('status').startswith('running'))
        pid = int(self.read('worker'))
        self.root.chmod(0o500)
        self.addCleanup(self.root.chmod, 0o700)
        os.kill(pid, signal.SIGKILL)
        self.wait_for(lambda: self.attempts() == 2)
        time.sleep(.3)
        self.assertIsNone(self.process.poll())
        new = int(self.read('worker'))
        self.assertNotEqual(new, pid)
        self.assertTrue(Path(f'/proc/{new}').exists())
        self.assertEqual(self.attempts(), 2)
        self.assertTrue(self.read('status').startswith('running'))  # stale, not fatal
        self.root.chmod(0o700)
        self.stop()
        self.assertEqual(self.process.returncode, 0)
        self.assertTrue(self.read('status').startswith('stopped'))

    def test_full_filesystem_drops_logs_and_keeps_a_noisy_app(self):
        self.start('noisy', faults=True)
        self.wait_for(lambda: self.attempts() == 1 and self.read('status').startswith('running'))
        pid = int(self.read('worker'))
        (self.root/'fail-write').touch()
        time.sleep(.5)
        # Output is still drained (the app never blocks on a full pipe).
        self.assertIsNone(self.process.poll())
        self.assertEqual(int(self.read('worker')), pid)
        self.assertTrue(Path(f'/proc/{pid}').exists())
        self.assertEqual(self.attempts(), 1)
        (self.root/'fail-write').unlink()
        resumed = time.time()

        def written_since():
            # Rotation renames current.log away for a moment.
            for name in ('current.log', 'previous.log'):
                try:
                    if (self.root/name).stat().st_mtime > resumed: return True
                except FileNotFoundError:
                    pass
            return False
        self.wait_for(written_since)
        self.stop()
        self.assertEqual(self.process.returncode, 0)
        self.assertTrue(self.read('status').startswith('stopped'))
        for name in ('current.log', 'previous.log'):
            self.assertLessEqual((self.root/name).stat().st_size, 4096)

    def test_full_filesystem_still_restarts_and_logging_recovers(self):
        self.start('steady', faults=True)
        self.wait_for(lambda: self.attempts() == 1 and self.read('status').startswith('running'))
        (self.root/'fail-write').touch()
        # A crash while nothing can be written is still restarted.
        os.kill(int(self.read('worker')), signal.SIGKILL)
        self.wait_for(lambda: self.attempts() == 2)
        time.sleep(.2)
        self.assertIsNone(self.process.poll())
        (self.root/'fail-write').unlink()
        time.sleep(.15)  # past LOG_RETRY_MS
        os.kill(int(self.read('worker')), signal.SIGKILL)
        self.wait_for(lambda: self.attempts() == 3 and self.read('status').startswith('running'))
        # The next file says what was lost.
        self.assertIn('log bytes dropped', self.read('current.log'))
        self.stop()
        self.assertEqual(self.process.returncode, 0)

    def test_pipe_and_fork_failures_back_off_and_recover(self):
        for marker, call in (('fail-pipe', 'pipe'), ('fail-fork', 'fork')):
            with self.subTest(call):
                for name in ('attempts', 'status', 'current.log', 'previous.log'):
                    (self.root/name).unlink(missing_ok=True)
                (self.root/marker).touch()
                self.start('steady', faults=True)
                self.wait_for(lambda: 'failures=3' in self.read('status'))
                self.assertIsNone(self.process.poll())
                self.assertEqual(self.attempts(), 0)
                time.sleep(.5)
                # The normal backoff (80, 160, then 200 ms), not a spin.
                log = self.read('previous.log') + self.read('current.log')
                self.assertGreaterEqual(log.count(f'supervise: {call}:'), 4)
                self.assertLess(log.count(f'supervise: {call}:'), 12)
                (self.root/marker).unlink()
                self.wait_for(lambda: self.attempts() == 1 and self.read('status').startswith('running'))
                self.stop()
                self.assertEqual(self.process.returncode, 0)


if __name__ == '__main__':
    unittest.main()
