#!/usr/bin/env python3
"""S61fpvos-usb-board: bridge mode's board id from the P1 ground unit."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'rootfs-overlay/etc/init.d/S61fpvos-usb-board'


class Tests(unittest.TestCase):
    def run_for(self, unit):
        with tempfile.TemporaryDirectory() as d:
            conf, device = Path(d) / 'fpvos-usb', Path(d) / 'p1-gnd-device'
            conf.write_text('GADGET=fpvos\nBOARD=p1-gnd\nPRODUCT=BETAFPV P1 - fpvOS\n')
            device.write_text(f'#!/bin/sh\necho {unit}\n' if unit else '#!/bin/sh\nexit 1\n')
            device.chmod(0o755)
            env = dict(os.environ, FPVOS_USB_CONF=str(conf), P1_GND_DEVICE=str(device))
            subprocess.run(['sh', str(SCRIPT), 'start'], env=env, check=True)
            return conf.read_text()

    def test_each_unit_names_its_board(self):
        for unit, board in (('goggles', 'p1-goggles'), ('goggles-pro', 'p1-goggles-pro'),
                            ('nano-vrx', 'p1-nano-vrx'), ('', 'p1-gnd'), ('other', 'p1-gnd')):
            text = self.run_for(unit)
            self.assertIn(f'\nBOARD={board}\n', text, unit)
            self.assertIn('PRODUCT=BETAFPV P1 - fpvOS', text)


if __name__ == '__main__':
    unittest.main()
