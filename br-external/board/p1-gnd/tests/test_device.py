#!/usr/bin/env python3
"""The P1 ground image tells its units apart by their device tree, and picks
each one's radio firmware and USB name from it."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

OVERLAY = Path(__file__).resolve().parents[1] / 'rootfs-overlay'
DEVICE = OVERLAY / 'usr/sbin/p1-gnd-device'


class Device(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.d = Path(temp.name)

    def tree(self, *compatible):
        p = self.d / 'compatible'
        p.write_bytes(b''.join(c.encode() + b'\0' for c in compatible))
        return p

    def device(self, *compatible):
        env = dict(os.environ, P1_GND_COMPATIBLE=str(self.tree(*compatible)))
        return subprocess.run(['sh', str(DEVICE)], env=env, capture_output=True, text=True)

    def sourced(self, name, *compatible):
        """A defaults file read the way its init script reads it."""
        env = dict(os.environ, P1_GND_COMPATIBLE=str(self.tree(*compatible)),
                   P1_GND_DEVICE=str(DEVICE))
        script = f'. "{OVERLAY}/etc/default/{name}"; set'
        r = subprocess.run(['sh', '-c', script], env=env, capture_output=True, text=True, check=True)
        out = {}
        for line in r.stdout.splitlines():
            k, _, v = line.partition('=')
            out[k] = v.strip("'")
        return out

    def test_units(self):
        self.assertEqual(self.device('betafpv,p1-goggle', 'artosyn,ar9311').stdout.strip(), 'goggles')
        self.assertEqual(self.device('betafpv,p1-nano-vrx', 'artosyn,ar9311').stdout.strip(), 'nano-vrx')
        self.assertEqual(self.device('betafpv,p1-goggle-pro', 'artosyn,ar9311').stdout.strip(), 'goggles-pro')

    def test_unknown_unit_refused(self):
        r = self.device('betafpv,p1-air', 'artosyn,ar9311')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, '')
        r = self.device('betafpv,p1-goggle-x')        # a whole name, not a prefix
        self.assertNotEqual(r.returncode, 0)

    def test_radio_firmware_per_unit(self):
        g = self.sourced('ar9311-radio', 'betafpv,p1-goggle', 'artosyn,ar9311')
        n = self.sourced('ar9311-radio', 'betafpv,p1-nano-vrx', 'artosyn,ar9311')
        self.assertIn('open8030.img', str(g))
        self.assertIn('open8030-nano-vrx.img', str(n))
        self.assertNotIn('open8030-nano-vrx', str(g))

    def test_radio_firmware_unknown_unit_starts_none(self):
        u = self.sourced('ar9311-radio', 'betafpv,p1-air')
        self.assertNotIn('open8030.img', str(u))
        self.assertNotIn('open8030-nano-vrx.img', str(u))

    def test_usb_name_per_unit(self):
        self.assertIn('P1 VRX - fpvOS', str(self.sourced('ar9311-usb', 'betafpv,p1-nano-vrx')))
        self.assertIn('goggles', str(self.sourced('ar9311-usb', 'betafpv,p1-goggle')))
        self.assertIn('P1 goggles Pro - fpvOS', str(self.sourced('ar9311-usb', 'betafpv,p1-goggle-pro')))


class Trees(unittest.TestCase):
    """What the shared image needs of both units' device trees."""
    BOARDS = Path(__file__).resolve().parents[2]
    UNITS = ('p1-goggle/dts/betafpv-p1-goggle.dts', 'p1-nano-vrx/dts/betafpv-p1-nano-vrx.dts',
             'p1-gnd/dts/betafpv-p1-goggle-pro.dts')
    RECOVERY = 'p1-gnd/dts/betafpv-p1-gnd.dts'      # a stock unit's RAM recovery, any ground unit
    TREES = UNITS + (RECOVERY,)

    def test_both_banks_under_the_names_the_updater_opens(self):
        """fpvos-update picks the bank per install and finds it by name."""
        for tree in self.TREES:
            text = (self.BOARDS / tree).read_text()
            for label, reg in (('kernel0', '0xa40000 0x600000'), ('kernel1', '0x1040000 0x600000'),
                               ('dtb0', '0x1640000 0x60000'), ('dtb1', '0x16a0000 0x60000'),
                               ('userapp0', '0x1700000 0x2d00000'), ('userapp1', '0x4400000 0x2d00000')):
                self.assertIn(f'label = "{label}"; reg = <{reg}>; }};', text, (tree, label))

    def test_keys_under_the_name_the_runtime_opens(self):
        """The pinned p1goggle runtime opens the evdev device p1-goggle-keys."""
        for tree in self.UNITS:
            self.assertIn('\tp1-goggle-keys {\n\t\tcompatible = "adc-keys";', (self.BOARDS / tree).read_text(), tree)

    def test_the_recovery_tree_is_no_units_and_drives_none_of_their_hardware(self):
        text = (self.BOARDS / self.RECOVERY).read_text()
        self.assertIn('compatible = "betafpv,p1-gnd", "artosyn,proxima-9311";', text)
        for unit in ('betafpv,p1-goggle', 'betafpv,p1-nano-vrx', 'betafpv,p1-goggle-pro'):
            self.assertNotIn(f'"{unit}"', text)
        # no screen, bridge, radio, SD card or keys; the factory volume stays read-only
        for absent in ('&dsi', '&vo', '&vpu', '&mmc0', '&mmc1', 'reset-gpios', 'adc-keys', 'lontium', 'panel@', '&i2c'):
            self.assertNotIn(absent, text, absent)
        self.assertIn('label = "factory"; reg = <0x200000 0x600000>; read-only;', text)
        # what the updater knows it by (backends/p1-gnd/config.h)
        config = (self.BOARDS.parent / 'package/fpvos-update/backends/p1-gnd/config.h').read_text()
        model = re.search(r'model = "([^"]+)";', text).group(1)
        self.assertIn(f'#define P1_MODEL_ANY "{model}"', config)
        self.assertIn('#define P1_COMPATIBLE_ANY "betafpv,p1-gnd"', config)

    def test_every_units_tree_is_one_the_updater_and_the_unit_know(self):
        """A tree's model and compatible are in the updater's list, its unit named by p1-gnd-device."""
        config = (self.BOARDS.parent / 'package/fpvos-update/backends/p1-gnd/config.h').read_text()
        device = (self.BOARDS / 'p1-gnd/rootfs-overlay/usr/sbin/p1-gnd-device').read_text()
        post = (self.BOARDS / 'p1-gnd/post-image.sh').read_text()
        for tree in self.UNITS:
            text = (self.BOARDS / tree).read_text()
            model = re.search(r'model = "([^"]+)";', text).group(1)
            unit = re.search(r'compatible = "(betafpv,[^"]+)"', text).group(1)
            self.assertRegex(config, rf'#define P1_MODEL(_ALT2?)? "{re.escape(model)}"', tree)
            self.assertRegex(config, rf'#define P1_COMPATIBLE(_ALT2?)? "{re.escape(unit)}"', tree)
            self.assertIn(f'*" {unit} "*)', device, tree)
            self.assertRegex(post, rf':{re.escape(Path(tree).stem)}[ ;]', tree)

    def test_status_led_is_opt_in_for_verified_p1_boards(self):
        for tree in self.UNITS + (self.RECOVERY,):
            text = (self.BOARDS / tree).read_text()
            self.assertEqual('betafpv,p1-vrx-status-led' in text,
                             tree.startswith(('p1-nano-vrx/', 'p1-goggle/')), tree)
        shared = (self.BOARDS / 'common/ar9311/dts/ar9311.dtsi').read_text()
        spi = shared.split('spi1: spi@1102000 {', 1)[1].split('};', 1)[0]
        self.assertIn('status = "disabled";', spi)

    def test_the_goggles_pro_tree_drives_its_bridge_not_the_goggles_panel(self):
        text = (self.BOARDS / 'p1-gnd/dts/betafpv-p1-goggle-pro.dts').read_text()
        self.assertIn('compatible = "betafpv,vr04-pro-display";\n\t\treg = <0x57>;', text)
        self.assertEqual(text.count('artosyn,display-profile = "p1-goggle-pro-1080p";'), 2)
        self.assertIn('gpios = <105 GPIO_ACTIVE_HIGH>;\n\t\toutput-high;', text)
        for absent in ('qiyang', 'pwm-backlight', 'lontium'):
            self.assertNotIn(absent, text, absent)
        # the rest is the goggles' board: same flash layout, keys, radio reset and memory
        goggles = (self.BOARDS / 'p1-goggle/dts/betafpv-p1-goggle.dts').read_text()
        for same in ('reset-gpios = <&gpio 23 GPIO_ACTIVE_LOW>;', 'reg = <0 0x29400000 0 0x06b00000>;',
                     'gpios = <100 GPIO_ACTIVE_HIGH>;'):
            self.assertIn(same, text); self.assertIn(same, goggles)


if __name__ == '__main__':
    unittest.main()
