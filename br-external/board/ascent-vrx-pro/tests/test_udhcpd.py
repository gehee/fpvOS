#!/usr/bin/env python3
"""S41udhcpd stop takes down the USB link's udhcpd only, never the WiFi
access point's (fpvos-wifi); this busybox has no pidfile support."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

BOARD = Path(__file__).resolve().parents[1]
S41 = BOARD / 'rootfs-overlay/etc/init.d/S41udhcpd'
WIFI = BOARD / 'rootfs-overlay/usr/sbin/fpvos-wifi'


class Stop(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.d = Path(temp.name)
        self.proc = self.d / 'proc'
        (self.d / 'bin').mkdir()
        # Two udhcpds, stood in for by sleeps: /proc/<pid>/cmdline says which
        # config each runs with, and pidof names them both.
        self.usb = self.daemon(b'udhcpd\0/etc/udhcpd.conf\0')
        self.wifi = self.daemon(b'udhcpd\0/run/fpvos-wifi/udhcpd.conf\0')
        pidof = self.d / 'bin/pidof'
        pidof.write_text(f'#!/bin/sh\necho {self.usb.pid} {self.wifi.pid}\n'); pidof.chmod(0o755)
        for name in ('killall',):
            p = self.d / 'bin' / name
            p.write_text(f'#!/bin/sh\necho "$0 $*" >> "{self.d}/killall"\n'); p.chmod(0o755)

    def daemon(self, cmdline):
        p = subprocess.Popen(['sleep', '60'])
        self.addCleanup(lambda: (p.kill(), p.wait()))
        (self.proc / str(p.pid)).mkdir(parents=True)
        (self.proc / str(p.pid) / 'cmdline').write_bytes(cmdline)
        return p

    def script(self, path):
        s = self.d / path.name
        s.write_text(path.read_text().replace('/proc/', f'{self.proc}/'))
        return s

    def env(self):
        return dict(os.environ, PATH=f'{self.d}/bin:/usr/bin:/bin')

    def test_stop_kills_the_usb_links_udhcpd_only(self):
        r = subprocess.run(['sh', str(self.script(S41)), 'stop'], env=self.env(),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.usb.wait(timeout=5), -15)
        self.assertIsNone(self.wifi.poll())
        self.assertFalse((self.d / 'killall').exists())

    def test_fpvos_wifi_finds_its_own_udhcpd_only(self):
        text = self.script(WIFI).read_text()
        fn = re.search(r'^our_udhcpd\(\) \{\n.*?^\}\n', text, re.S | re.M).group(0)
        s = self.d / 'ours.sh'
        s.write_text(f'RUN=/run/fpvos-wifi\n{fn}our_udhcpd\n')
        out = subprocess.run(['sh', str(s)], env=self.env(), capture_output=True, text=True).stdout
        self.assertEqual(out.split(), [str(self.wifi.pid)])

    def test_no_pidfile_or_killall(self):
        text = S41.read_text()
        self.assertNotIn('killall', text)
        self.assertNotIn('$PIDF', text)


if __name__ == '__main__':
    unittest.main()
