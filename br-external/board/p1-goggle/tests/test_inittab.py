#!/usr/bin/env python3
"""Shutdown order of the P1 goggle image's inittab."""
from pathlib import Path
import unittest

BOARD = Path(__file__).resolve().parents[1]


def steps(action):
    text = (BOARD/'rootfs-overlay/etc/inittab').read_text()
    return [line.split(':', 3)[3] for line in text.splitlines()
            if line.split(':', 3)[2:3] == [action]]


class Shutdown(unittest.TestCase):
    def test_watchdog_daemon_started_at_boot(self):
        self.assertTrue(any(s.startswith('/sbin/watchdog ') for s in steps('sysinit')))

    def test_watchdog_daemon_killed_first_without_magic_close(self):
        # SIGKILL, not SIGTERM: busybox's watchdog disarms on SIGTERM, and a
        # hung shutdown step would then never reset the goggles.
        self.assertEqual(steps('shutdown')[0], '/usr/bin/killall -KILL watchdog')

    def test_kestrel_stopped_before_its_storage(self):
        shutdown = steps('shutdown')
        self.assertLess(shutdown.index('/etc/init.d/S60kestrel-gnd stop'),
                        shutdown.index('/etc/init.d/S45ar9311-sd stop'))
        self.assertEqual(shutdown[-1], '/bin/umount -a -r')


if __name__ == '__main__':
    unittest.main()
