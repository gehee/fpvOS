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


class Boot(unittest.TestCase):
    """The scripts are started by name (no rcS): each one has to be listed."""
    def setUp(self):
        text = (BOARD/'source-rootfs-overlay/etc/inittab').read_text()
        self.steps = [line.split(':', 3)[3] for line in text.splitlines()
                      if line.startswith('::sysinit:')]

    def test_saved_bridge_mode_restored_after_settings_and_kestrel(self):
        # fpvos-usb's SAVED_MODE lives on /persist (S45) and bridge mode takes
        # the chip from Kestrel (S60): S61 after both, or bridge never comes back.
        restore = self.steps.index('/etc/init.d/S61fpvos-usb start')
        self.assertLess(self.steps.index('/etc/init.d/S45settings start'), restore)
        self.assertLess(self.steps.index('/etc/init.d/S60kestrel-air start'), restore)


class RecoveryShutdown(unittest.TestCase):
    """The embedded recovery (fpvos-recovery): its reboot ends the updater's
    install, and the computer has to see the unit leave first."""
    def setUp(self):
        text = (BOARD.parents[1]/'package/fpvos-recovery/src/inittab').read_text()
        self.steps = [line.split(':', 3)[3] for line in text.splitlines()
                      if line.startswith('::shutdown:')]

    def test_usb_gadget_unbound_before_the_reset(self):
        usb = self.steps.index('/etc/init.d/S40ar9311-usb stop')
        pause = self.steps.index('/bin/sleep 1')
        self.assertLess(usb, pause)
        self.assertLess(pause, self.steps.index('/bin/umount -a -r'))


if __name__ == '__main__':
    unittest.main()
