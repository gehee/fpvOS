#!/usr/bin/env python3
"""S30usbgadget says what came up: the gadget bound to a UDC and usb0
configured, or which of the two did not happen. The identity host tools
depend on (serial number, MACs) is unchanged."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

BOARD = Path(__file__).resolve().parents[1]
SCRIPT = BOARD / 'rootfs-overlay/etc/init.d/S30usbgadget'

STANDINS = {
    'modprobe': '#!/bin/sh\n',
    'mountpoint': '#!/bin/sh\n',
    'sleep': '#!/bin/sh\n',
    'ifconfig': '#!/bin/sh\necho "ifconfig $*" >> "$T/calls"\n[ -z "$NO_USB0" ]\n',
}


class Start(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.d = Path(temp.name)
        (self.d / 'bin').mkdir(); (self.d / 'udc').mkdir()
        for name, text in STANDINS.items():
            p = self.d / 'bin' / name; p.write_text(text); p.chmod(0o755)
        text = SCRIPT.read_text()
        text = text.replace('/sys/kernel/config/usb_gadget/vrx', str(self.d / 'gadget'))
        text = text.replace('/sys/class/udc', str(self.d / 'udc'))
        self.script = self.d / 'S30usbgadget'
        self.script.write_text(text)

    def start(self, udc='fcc00000.dwc3', **env):
        if udc:
            (self.d / 'udc' / udc).mkdir()
        r = subprocess.run(['sh', str(self.script), 'start'], capture_output=True, text=True,
                           env=dict(os.environ, PATH=f'{self.d}/bin:/usr/bin:/bin', T=str(self.d), **env))
        return r.stdout.strip().splitlines()[-1]

    def gadget(self, rel):
        return (self.d / 'gadget' / rel).read_text().strip()

    def test_up(self):
        self.assertEqual(self.start(), 'usbgadget: NCM+ACM up on fcc00000.dwc3, usb0=192.168.3.1')
        self.assertEqual(self.gadget('UDC'), 'fcc00000.dwc3')

    def test_no_udc(self):
        line = self.start(udc=None)
        self.assertIn('no USB device controller', line)
        self.assertNotIn(' up', line)
        self.assertFalse((self.d / 'calls').exists())

    def test_usb0_never_appears(self):
        line = self.start(NO_USB0='1')
        self.assertIn('usb0 never came up', line)
        self.assertEqual(len((self.d / 'calls').read_text().splitlines()), 8)

    def test_identity_unchanged(self):
        self.start()
        self.assertEqual(self.gadget('strings/0x409/serialnumber'), '2020')
        self.assertEqual(self.gadget('functions/ncm.usb0/dev_addr'), '02:00:de:ad:be:ef')
        self.assertEqual(self.gadget('functions/ncm.usb0/host_addr'), '02:00:de:ad:be:ed')
        self.assertEqual((self.gadget('idVendor'), self.gadget('idProduct')), ('0x1d77', '0xa4a2'))


if __name__ == '__main__':
    unittest.main()
