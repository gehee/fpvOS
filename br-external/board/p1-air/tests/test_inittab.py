#!/usr/bin/env python3
"""Shutdown order of the P1 source image's inittab."""
from pathlib import Path
import unittest

BOARD = Path(__file__).resolve().parents[1]


class Shutdown(unittest.TestCase):
    def setUp(self):
        text = (BOARD/'source-rootfs-overlay/etc/inittab').read_text()
        self.steps = [line.split(':', 3)[3] for line in text.splitlines()
                      if line.startswith('::shutdown:')]

    def test_watchdog_daemon_killed_first_without_magic_close(self):
        # SIGKILL, not SIGTERM: busybox's watchdog disarms on SIGTERM.
        self.assertEqual(self.steps[0], '/usr/bin/killall -KILL watchdog')

    def test_bridge_left_before_the_usb_gadget_goes_down(self):
        bridge = self.steps.index('/usr/sbin/fpvos-usb shutdown')
        usb = self.steps.index('/etc/init.d/S40ar9311-usb stop')
        self.assertLess(bridge, usb)


if __name__ == '__main__':
    unittest.main()
