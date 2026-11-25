#!/usr/bin/env python3
"""Shutdown order of the SteadyDigital image's inittab."""
from pathlib import Path
import unittest

BOARD = Path(__file__).resolve().parents[1]


class Shutdown(unittest.TestCase):
    def setUp(self):
        text = (BOARD/'rootfs-overlay/etc/inittab').read_text()
        self.steps = [line.split(':', 3)[3] for line in text.splitlines()
                      if line.startswith('::shutdown:')]

    def test_bridge_left_first(self):
        # A reboot, an update or "stock" from bridge mode: the bridge holds the
        # gadget's FunctionFS endpoints, and unbinding under them hangs.
        self.assertEqual(self.steps[0],
                         "/bin/sh -c '[ ! -x /usr/sbin/fpvos-usb ] || /usr/sbin/fpvos-usb shutdown'")

    def test_bridge_left_before_the_usb_gadget_goes_down(self):
        bridge = next(i for i, s in enumerate(self.steps) if 'fpvos-usb shutdown' in s)
        self.assertLess(bridge, self.steps.index('/etc/init.d/S40ar9311-usb stop'))


class Boot(unittest.TestCase):
    def setUp(self):
        text = (BOARD/'rootfs-overlay/etc/inittab').read_text()
        self.steps = [line.split(':', 3)[3] for line in text.splitlines()
                      if line.startswith('::sysinit:')]

    def test_saved_bridge_mode_restored_after_kestrel(self):
        # Bridge mode takes the radio from Kestrel: S61 after S60.
        kestrel = next(i for i, s in enumerate(self.steps) if 'S60kestrel-gnd start' in s)
        restore = next(i for i, s in enumerate(self.steps) if 'S61fpvos-usb start' in s)
        self.assertLess(kestrel, restore)


if __name__ == '__main__':
    unittest.main()
