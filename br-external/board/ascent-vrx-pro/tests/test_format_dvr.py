#!/usr/bin/env python3
"""The VRX Pro's fpvos-format-dvr: one format at a time, run against stand-ins
for the card, mount and init scripts (the stand-in partition is a plain file)."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

BOARD = Path(__file__).resolve().parents[1]
SCRIPT = BOARD/'rootfs-overlay/usr/sbin/fpvos-format-dvr'


@unittest.skipUnless(shutil.which('flock') and shutil.which('setsid'), 'needs flock and setsid')
class OneFormatAtATime(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name).resolve()
        self.bin = root/'bin'; self.bin.mkdir()
        text = SCRIPT.read_text()
        text = text.replace('PATH=/sbin:', f'PATH={self.bin}:/sbin:')
        text = text.replace('[ -b "$PART" ]', '[ -e "$PART" ]')
        for prefix in ('/dev/', '/run/', '/sys/', '/proc/', '/etc/init.d/', '/media/'):
            text = text.replace(prefix, str(root)+prefix)
        self.script = root/'fpvos-format-dvr'
        self.script.write_text(text); self.script.chmod(0o755)
        for d in ('dev', 'run', 'proc', 'etc/init.d', 'media/dvr', 'sys/class/block/mmcblk1p4'):
            (root/d).mkdir(parents=True)
        (root/'dev/mmcblk1p4').write_text('')
        (root/'sys/class/block/mmcblk1p4/size').write_text('62333952\n')
        (root/'proc/mounts').write_text('')
        for name in ('mkfs.exfat', 'mount', 'umount', 'sync'):
            self.command(name, f'echo "{name}" >> "{root}/calls"')
        self.command('mountpoint', 'exit 1')
        # The receiver's stop takes a while, so the first worker is still
        # running when the second start comes; its start records whether it
        # was handed the lock.
        s70 = root/'etc/init.d/S70kestrel'
        s70.write_text(f'#!/bin/sh\necho "S70kestrel $* $([ -e /proc/self/fd/8 ] && echo with-lock)" >> "{root}/calls"\n'
                       '[ "$1" != stop ] || sleep 1\n')
        s70.chmod(0o755)

    def command(self, name, body):
        p = self.bin/name; p.write_text(f'#!/bin/sh\n{body}\n'); p.chmod(0o755)

    def start(self):
        return subprocess.run(['sh', str(self.script), 'start'], capture_output=True, text=True, timeout=10)

    def calls(self):
        p = self.root/'calls'
        return p.read_text() if p.exists() else ''

    def status(self):
        p = self.root/'run/fpvos-format-dvr.status'
        return p.read_text() if p.exists() else ''

    def wait_for(self, predicate, timeout=10):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if predicate(): return
            time.sleep(.05)
        self.fail('timed out: ' + self.status())

    def test_second_start_refused_while_a_worker_runs(self):
        first = self.start()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.wait_for(lambda: 'S70kestrel stop' in self.calls())
        second = self.start()
        self.assertNotEqual(second.returncode, 0)
        self.assertIn('A format is already running', second.stdout)
        self.wait_for(lambda: self.status().startswith('ok'))
        self.assertEqual(self.calls().count('mkfs.exfat'), 1)

    def test_the_restarted_receiver_does_not_keep_the_lock(self):
        self.assertEqual(self.start().returncode, 0)
        self.wait_for(lambda: self.status().startswith('ok'))
        self.wait_for(lambda: 'S70kestrel start' in self.calls())
        starts = [l for l in self.calls().splitlines() if l.startswith('S70kestrel start')]
        self.assertTrue(starts)
        self.assertFalse([l for l in starts if 'with-lock' in l])
        # And a later format can run.
        self.assertEqual(self.start().returncode, 0)

    def test_a_worker_without_the_lock_does_nothing(self):
        r = subprocess.run(['sh', str(self.script), 'worker'], capture_output=True, text=True, timeout=10)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('mkfs.exfat', self.calls())


if __name__ == '__main__':
    unittest.main()
