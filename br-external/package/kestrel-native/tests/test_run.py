#!/usr/bin/env python3
"""The kestrel-gnd launcher (run) against a stand-in root: state and backlight
problems cost settings or brightness, never the receiver's start."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]


class Launcher(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Resolved: run compares readlink -f results with the card's path.
        self.root = Path(self.tmp.name).resolve()
        text = (PACKAGE/'run').read_text()
        for prefix in ('/var/lib/', '/run/', '/etc/default/', '/proc/', '/mnt/sd', '/opt/kestrel'):
            text = text.replace(prefix, str(self.root)+prefix)
        self.script = self.root/'launcher'
        self.script.write_text(text)
        for d in ('var/lib', 'run/kestrel-gnd', 'etc/default', 'proc', 'mnt/sd', 'opt/kestrel/bin'):
            (self.root/d).mkdir(parents=True, exist_ok=True)
        (self.root/'proc/mounts').write_text('')
        app = self.root/'opt/kestrel/bin/kestrel-gnd'
        app.write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done > "$ARGS"\n')
        app.chmod(0o755)
        self.args = self.root/'args'

    def defaults(self, text):
        (self.root/'etc/default/kestrel-native').write_text(text)

    def run_launcher(self):
        r = subprocess.run(['sh', str(self.script)], capture_output=True, text=True,
                           env={**os.environ, 'ARGS': str(self.args)})
        self.assertEqual(r.returncode, 0, r.stderr)
        args = self.args.read_text().splitlines()
        return r, dict(zip(args[::2], args[1::2]))

    def test_writable_state_is_used(self):
        r, args = self.run_launcher()
        self.assertEqual(args['--preferences'], str(self.root/'var/lib/kestrel/ui.conf'))
        self.assertEqual(args['--pairing'], str(self.root/'var/lib/kestrel/peer'))
        self.assertNotIn('temporary', r.stderr)

    def test_dangling_card_link_falls_back_to_run(self):
        # Ascent VRX: S46kestrel-state linked /var/lib/kestrel to the card,
        # which has since been unmounted.
        (self.root/'var/lib/kestrel').symlink_to(self.root/'mnt/sd/fpvos/kestrel')
        r, args = self.run_launcher()
        self.assertEqual(args['--preferences'], str(self.root/'run/kestrel-state/ui.conf'))
        self.assertEqual(args['--settings'], str(self.root/'run/kestrel-state/receiver.conf'))
        self.assertIn('settings and pairing are temporary', r.stderr)
        self.assertTrue((self.root/'run/kestrel-state').is_dir())
        # The link's target is not created in the RAM root under /mnt/sd.
        self.assertFalse((self.root/'mnt/sd/fpvos').exists())

    def test_unwritable_state_falls_back_to_run(self):
        if os.geteuid() == 0:
            self.skipTest('root ignores directory permissions')
        state = self.root/'var/lib/kestrel'
        state.mkdir()
        state.chmod(0o500)
        self.addCleanup(state.chmod, 0o700)
        r, args = self.run_launcher()
        self.assertEqual(args['--pairing'], str(self.root/'run/kestrel-state/peer'))
        self.assertIn('temporary', r.stderr)

    def test_backlight_set_and_unblanked(self):
        light = self.root/'sys/class/backlight/backlight'
        light.mkdir(parents=True)
        self.defaults(f'KESTREL_NATIVE_BACKLIGHT={light}/brightness\nKESTREL_NATIVE_BRIGHTNESS=7\n')
        r, args = self.run_launcher()
        self.assertEqual((light/'brightness').read_text(), '7\n')
        self.assertEqual((light/'bl_power').read_text(), '0\n')
        self.assertNotIn('cannot', r.stderr)

    def test_missing_backlight_node_still_starts(self):
        self.defaults(f'KESTREL_NATIVE_BACKLIGHT={self.root}/sys/class/backlight/none/brightness\n')
        r, args = self.run_launcher()
        self.assertIn('cannot set', r.stderr)
        self.assertIn('cannot unblank', r.stderr)
        self.assertIn('--recordings', args)

    def test_no_radio_and_recordings_without_card(self):
        self.defaults('KESTREL_NATIVE_NO_RADIO=1\n')
        r, _ = self.run_launcher()
        args = self.args.read_text().splitlines()
        self.assertEqual(args[-1], '--no-radio')
        self.assertEqual(args[args.index('--recordings')+1], str(self.root/'run/kestrel-gnd/no-sd/recordings'))

    def test_recordings_on_a_writable_card(self):
        (self.root/'proc/mounts').write_text(f'/dev/mmcblk0p1 {self.root}/mnt/sd vfat rw,noexec 0 0\n')
        _, args = self.run_launcher()
        self.assertEqual(args['--recordings'], str(self.root/'mnt/sd/fpvos/recordings'))
        self.assertTrue((self.root/'mnt/sd/fpvos/recordings').is_dir())


if __name__ == '__main__':
    unittest.main()
