#!/usr/bin/env python3
"""fpvos-wifi keeps the access point's clients off SSH and the USB link."""
from pathlib import Path
import ipaddress
import os
import re
import subprocess
import tempfile
import unittest

BOARD = Path(__file__).resolve().parents[1]
WIFI = BOARD / 'rootfs-overlay/usr/sbin/fpvos-wifi'

# A stand-in iptables: -C answers from the rules inserted so far, -I records
# one (or fails, with FAIL_INSERT set); every call is logged.
FAKE = r'''#!/bin/sh
echo "$*" >> "$LOG"
op=$1; shift
case $op in
    -C) grep -qxF -- "$*" "$RULES" 2>/dev/null ;;
    -I) [ -z "$FAIL_INSERT" ] || exit 1; echo "$*" >> "$RULES" ;;
    *) exit 2 ;;
esac
'''


class Guard(unittest.TestCase):
    def setUp(self):
        self.text = WIFI.read_text()
        rules = re.search(r"^GUARD_RULES='.*?'\n", self.text, re.S | re.M).group(0)
        guard = re.search(r'^guard\(\) \{\n.*?^\}\n', self.text, re.S | re.M).group(0)
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.d = Path(temp.name)
        (self.d / 'bin').mkdir()
        (self.d / 'guard.sh').write_text(rules + guard + 'guard\n')

    def run_guard(self, iptables=True, **env):
        fake = self.d / 'bin/iptables'
        if iptables:
            fake.write_text(FAKE); fake.chmod(0o755)
        else:
            fake.unlink(missing_ok=True)
        e = dict(os.environ, PATH=f'{self.d}/bin:/usr/bin:/bin', LOG=str(self.d / 'log'), RULES=str(self.d / 'rules'), **env)
        return subprocess.run(['sh', str(self.d / 'guard.sh')], env=e).returncode

    def rules(self):
        path = self.d / 'rules'
        return path.read_text().splitlines() if path.exists() else []

    def test_drops_ssh_and_the_usb_link_from_wlan0(self):
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.rules(), ['INPUT -i wlan0 -d 192.168.3.0/24 -j DROP',
                                        'INPUT -i wlan0 -p tcp --dport 22 -j DROP'])

    def test_a_second_start_adds_nothing(self):
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(len(self.rules()), 2)

    def test_failure_is_reported(self):
        self.assertNotEqual(self.run_guard(FAIL_INSERT='1'), 0)
        self.assertNotEqual(self.run_guard(iptables=False), 0)

    def test_the_rules_cover_the_address_dropbear_listens_on(self):
        args = re.search(r'^DROPBEAR_ARGS="-p ([0-9.]+):22"$',
                         (BOARD / 'rootfs-overlay/etc/default/dropbear').read_text(), re.M).group(1)
        usb = re.search(r'-d ([0-9./]+) -j DROP', self.text).group(1)
        self.assertIn(ipaddress.ip_address(args), ipaddress.ip_network(usb))
        self.assertIn('192.168.3.1', (BOARD / 'rootfs-overlay/etc/init.d/S30usbgadget').read_text())


class Start(unittest.TestCase):
    def test_guard_comes_before_the_ap_and_stops_it_on_failure(self):
        start = re.search(r'^start\(\) \{\n.*?^\}\n', WIFI.read_text(), re.S | re.M).group(0)
        guard = start.index('guard ||')
        self.assertLess(guard, start.index('ifconfig wlan0 $ADDR'))
        self.assertLess(guard, start.index('hostapd -B'))
        self.assertIn('stop; return 1', start[guard:start.index('\n', guard)])


if __name__ == '__main__':
    unittest.main()
