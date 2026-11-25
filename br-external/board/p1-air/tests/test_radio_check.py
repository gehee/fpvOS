#!/usr/bin/env python3
"""S47radio-check: a bounded reboot when the radio did not come up, run
against stand-ins for /dev/arlink0, /proc/mounts, /persist and reboot."""
from pathlib import Path
import subprocess
import tempfile
import unittest

BOARD = Path(__file__).resolve().parents[1]
SCRIPT = BOARD/'source-rootfs-overlay/etc/init.d/S47radio-check'
INITTAB = BOARD/'source-rootfs-overlay/etc/inittab'


class RadioCheck(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        (root/'bin').mkdir(); (root/'proc').mkdir(); (root/'persist').mkdir(); (root/'dev').mkdir()
        text = SCRIPT.read_text().replace('PATH=/sbin:', f'PATH={root}/bin:/sbin:')
        text = text.replace('[ -c /dev/arlink0 ]', '[ -e /dev/arlink0 ]')  # the stand-in is a plain file
        for p in ('/dev/arlink0', '/proc/mounts', '/dev/kmsg'):
            text = text.replace(p, f'{root}{p}')
        text = text.replace('persist=/persist', f'persist={root}/persist')
        self.script = root/'S47radio-check'; self.script.write_text(text)
        for name, body in (('reboot', f'echo reboot >> {root}/calls'), ('sleep', ':'), ('sync', ':')):
            p = root/'bin'/name; p.write_text(f'#!/bin/sh\n{body}\n'); p.chmod(0o755)
        self.mounted(True)

    def mounted(self, yes):
        line = f'/dev/ubi0_0 {self.root}/persist ubifs rw,nosuid,nodev,noexec 0 0\n' if yes else ''
        (self.root/'proc/mounts').write_text(line)

    def radio(self, up):
        p = self.root/'dev/arlink0'
        if up: p.write_text('')
        elif p.exists(): p.unlink()

    def run_check(self):
        r = subprocess.run(['sh', str(self.script), 'start'], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def reboots(self):
        p = self.root/'calls'
        return p.read_text().count('reboot') if p.exists() else 0

    def count(self):
        p = self.root/'persist/fpvos/radio-reboots'
        return p.read_text().strip() if p.exists() else None

    def test_radio_up_does_nothing(self):
        self.radio(True)
        self.run_check()
        self.assertEqual(self.reboots(), 0)
        self.assertIsNone(self.count())

    def test_no_radio_reboots_twice_then_stays_up(self):
        self.radio(False)
        self.run_check(); self.assertEqual((self.reboots(), self.count()), (1, '1'))
        self.run_check(); self.assertEqual((self.reboots(), self.count()), (2, '2'))
        out = self.run_check()
        self.assertEqual(self.reboots(), 2)
        self.assertIn('staying up', out)

    def test_radio_up_clears_the_count(self):
        self.radio(False); self.run_check()
        self.radio(True); self.run_check()
        self.assertIsNone(self.count())
        self.radio(False); self.run_check()
        self.assertEqual(self.count(), '1')

    def test_no_reboot_without_the_settings_volume(self):
        self.mounted(False); self.radio(False)
        self.assertIn('staying up', self.run_check())
        self.assertEqual(self.reboots(), 0)

    def test_a_garbled_count_starts_over(self):
        self.radio(False)
        (self.root/'persist/fpvos').mkdir()
        (self.root/'persist/fpvos/radio-reboots').write_text('x\n')
        self.run_check()
        self.assertEqual(self.count(), '1')


class Order(unittest.TestCase):
    def test_after_the_radio_and_settings_before_kestrel(self):
        steps = [l.split(':', 3)[3] for l in INITTAB.read_text().splitlines() if l.startswith('::sysinit:')]
        at = lambda s: steps.index(f'/etc/init.d/{s} start')
        self.assertLess(at('S44ar9311-radio'), at('S47radio-check'))
        self.assertLess(at('S45settings'), at('S47radio-check'))
        self.assertLess(at('S47radio-check'), at('S60kestrel-air'))


if __name__ == '__main__':
    unittest.main()
