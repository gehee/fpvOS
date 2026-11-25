#!/usr/bin/env python3
"""bb_only.sh uploads the baseband firmware and radio config as a matched
pair: Open8030 with open8030.json, stock's firmware with a stock profile's
config; an unknown profile falls back to the default pair, and says so."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

BOARD = Path(__file__).resolve().parents[1]
BB_ONLY = BOARD / 'rootfs-overlay/ar8030soc/bb_only.sh'
STOCK_FW = 'bb_demo_cx485_2PA.img'


class Pair(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.d = Path(temp.name)
        fn = re.search(r'^select_pair\(\) \{\n.*?^\}\n', BB_ONLY.read_text(), re.S | re.M).group(0)
        for real, name in (('/usrdata/bb_profile', 'bb_profile'),
                           ('/etc/kestrel/kestrel-gnd.yaml', 'kestrel-gnd.yaml'),
                           ('/lib/firmware/open8030.img', 'open8030.img')):
            fn = fn.replace(real, str(self.d / name))
        (self.d / 'select.sh').write_text(fn + 'select_pair\necho "PAIR $BB_PROFILE $BB_FW $BB_CFG"\n')

    def select(self, profile=None, open8030=True, stock_setting=False, **env):
        (self.d / 'bb_profile').unlink(missing_ok=True)
        (self.d / 'open8030.img').unlink(missing_ok=True)
        if profile is not None:
            (self.d / 'bb_profile').write_text(profile + '\n')
        if open8030:
            (self.d / 'open8030.img').write_text('fw')
        (self.d / 'kestrel-gnd.yaml').write_text(
            'ar8030_firmware: 0\n' if stock_setting else 'ar8030_firmware: 1\n')
        e = {k: v for k, v in os.environ.items() if not k.startswith('BB_')}
        e.update(env)
        r = subprocess.run(['sh', str(self.d / 'select.sh')], env=e, capture_output=True, text=True, check=True)
        lines = r.stdout.splitlines()
        self.log = [l for l in lines if not l.startswith('PAIR ')]
        return tuple(lines[-1].split()[1:])

    def test_default_is_open8030_with_its_config(self):
        self.assertEqual(self.select(), ('caddx', 'open8030.img', 'open8030.json'))
        self.assertEqual(self.log, [])

    def test_stock_setting_or_no_image_is_stock_with_the_caddx_config(self):
        pair = ('caddx', STOCK_FW, 'bb_config_gnd_pro.json')
        self.assertEqual(self.select(stock_setting=True), pair)
        self.assertEqual(self.select(open8030=False), pair)

    def test_unknown_profile_falls_back_to_the_default_pair(self):
        self.assertEqual(self.select('bogus'), ('caddx', 'open8030.img', 'open8030.json'))
        self.assertIn("unknown bb profile 'bogus'", self.log[0])
        self.assertEqual(self.select('bogus', open8030=False), ('caddx', STOCK_FW, 'bb_config_gnd_pro.json'))

    def test_try_profile_with_stock_firmware(self):
        self.assertEqual(self.select('try', stock_setting=True), ('try', STOCK_FW, 'bb_config_try.json'))
        self.assertEqual(self.select(BB_PROFILE='try', open8030=False), ('try', STOCK_FW, 'bb_config_try.json'))

    def test_try_profile_under_open8030_is_said_not_to_apply(self):
        self.assertEqual(self.select('try'), ('try', 'open8030.img', 'open8030.json'))
        self.assertTrue(any("'try' is a config for stock's firmware" in l for l in self.log), self.log)

    def test_the_environment_wins_over_its_half(self):
        self.assertEqual(self.select(BB_FW='bb_demo_cx485_2PA_18.21.10.img', BB_PROFILE='try'),
                         ('try', 'bb_demo_cx485_2PA_18.21.10.img', 'bb_config_try.json'))
        self.assertEqual(self.select(BB_FW='open8030.img', open8030=False, stock_setting=True),
                         ('caddx', 'open8030.img', 'open8030.json'))
        self.assertEqual(self.select(BB_CFG='mine.json', stock_setting=True), ('caddx', STOCK_FW, 'mine.json'))

    def test_never_open8030_firmware_with_a_stock_config(self):
        for profile in ('caddx', 'try', 'bogus', ''):
            for stock in (False, True):
                _, fw, cfg = self.select(profile, stock_setting=stock)
                self.assertEqual(fw.startswith('open8030'), cfg == 'open8030.json', (profile, stock, fw, cfg))


if __name__ == '__main__':
    unittest.main()
