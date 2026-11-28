#!/usr/bin/env python3
"""fpvos-format-dvr's start against a stand-in card, sysfs and init scripts:
one worker at a time. The stand-in card is a plain file, so a worker stops at
"the card was removed" before dd, fdisk or mkfs would run."""
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

BOARD = Path(__file__).resolve().parents[1]
# shared by the AR9311 receivers (common/ar9311's overlay): the Ascent VRX,
# the SteadyDigital and the P1 ground units
SCRIPT = BOARD.parent/'common/ar9311/rootfs-overlay/usr/sbin/fpvos-format-dvr'


@unittest.skipUnless(shutil.which('flock') and shutil.which('setsid'), 'needs flock and setsid')
class OneFormatAtATime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = root = Path(self.tmp.name).resolve()
        self.bin = root/'bin'
        text = SCRIPT.read_text()
        text = text.replace('PATH=/sbin:', f'PATH={self.bin}:/sbin:')
        text = text.replace('/dev/$name', f'{root}/dev/$name')
        for prefix in ('/run/', '/sys/', '/proc/', '/mnt/sd', '/etc/init.d/', '/var/lib/'):
            text = text.replace(prefix, str(root)+prefix)
        self.script = root/'fpvos-format-dvr'
        self.script.write_text(text)
        self.script.chmod(0o755)
        for d in ('run', 'proc', 'mnt/sd', 'etc/init.d', 'var/lib', 'dev', 'sys/class/block'):
            (root/d).mkdir(parents=True)
        (root/'proc/mounts').write_text('')
        card = root/'sys/devices/platform/1c00000.mmc/mmc_host/mmc0/mmc0:aaaa/block/mmcblk0'
        (card/'device').mkdir(parents=True)
        (card/'device/type').write_text('SD\n')
        (card/'size').write_text('62333952\n')
        (root/'sys/class/block/mmcblk0').symlink_to(card)
        (root/'dev/mmcblk0').write_text('')  # not a block device
        self.bin.mkdir()
        self.command('mkfs.exfat', 'exit 0')
        self.command('pidof', 'exit 1')
        self.command('mountpoint', 'exit 1')
        # The receiver's stop takes a while: the worker is still running.
        for name, body in (('S60kestrel-gnd', '[ "$1" != stop ] || sleep 1'),
                           ('S45ar9311-sd', ':'), ('S46kestrel-state', ':')):
            p = root/'etc/init.d'/name
            p.write_text(f'#!/bin/sh\necho "{name} $*" >> "{root}/calls"\n{body}\n')
            p.chmod(0o755)

    def command(self, name, body):
        p = self.bin/name
        p.write_text(f'#!/bin/sh\n{body}\n')
        p.chmod(0o755)

    def start(self):
        return subprocess.run(['sh', str(self.script), 'start'], capture_output=True,
                              text=True, timeout=10)

    def status(self):
        try: return (self.root/'run/fpvos-format-dvr.status').read_text()
        except FileNotFoundError: return ''

    def wait_for(self, predicate, timeout=10):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.05)
        self.fail('timed out: ' + self.status())

    def test_second_start_refused_while_a_worker_runs(self):
        first = self.start()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn('Formatting SD card, 31.9 GB', first.stdout)
        self.wait_for(lambda: 'S60kestrel-gnd stop' in (self.root/'calls').read_text()
                      if (self.root/'calls').exists() else False)
        second = self.start()
        self.assertNotEqual(second.returncode, 0)
        self.assertIn('already running', second.stdout)
        # The first worker carries on to its own outcome.
        self.wait_for(lambda: self.status().startswith('failed'))
        self.assertEqual(self.status(), 'failed the card was removed\n')
        self.assertEqual((self.root/'calls').read_text().count('S60kestrel-gnd stop'), 1)
        # Once it is done, a new start is accepted - nothing it started kept the lock.
        self.wait_for(lambda: self.start_is_free())
        third = self.start()
        self.assertEqual(third.returncode, 0, third.stdout + third.stderr)
        self.wait_for(lambda: self.start_is_free())

    def start_is_free(self):
        with open(self.root/'run/fpvos-format-dvr.lock', 'a') as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return False
            fcntl.flock(f, fcntl.LOCK_UN)
            return True

    def test_start_refused_while_the_lock_is_held(self):
        with open(self.root/'run/fpvos-format-dvr.lock', 'a') as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            r = self.start()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('already running', r.stdout)
        self.assertEqual(self.status(), '')
        self.assertFalse((self.root/'calls').exists())

    def test_worker_without_the_lock_does_nothing(self):
        r = subprocess.run(['sh', str(self.script), 'worker', 'restart'], capture_output=True,
                           text=True, timeout=10)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.status(), '')
        self.assertFalse((self.root/'calls').exists())


if __name__ == '__main__':
    unittest.main()
