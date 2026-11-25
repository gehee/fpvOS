#!/usr/bin/env python3
"""The goggles' update-helper USB modes: the image has no fpvOS_usb, so a
host's "normal" is already true and "bridge" is refused by name."""
from pathlib import Path
import subprocess
import unittest

HELPER = Path(__file__).resolve().parents[4]/'br-external/package/fpvos-update/backends/p1-goggle/update-helper'


class UsbModes(unittest.TestCase):
    def run_helper(self, *args):
        return subprocess.run(['sh', str(HELPER), *args], capture_output=True, text=True, timeout=10)

    def test_normal_is_a_no_op_success(self):
        r = self.run_helper('normal')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout + r.stderr, '')

    def test_bridge_is_refused_clearly(self):
        r = self.run_helper('bridge')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotEqual(r.returncode, 127)
        self.assertIn('no bridge mode on this board', r.stderr)

    def test_no_fpvos_usb_reference(self):
        self.assertNotIn('fpvos-usb', HELPER.read_text())


if __name__ == '__main__':
    unittest.main()
