#!/usr/bin/env python3
"""post-build.sh keeps Artosyn's radio host stack out whenever the
configuration selects ar-libre, wherever its arlink.ko was installed, and
fails a build that selects ar-libre without the module."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

BOARD = Path(__file__).resolve().parents[1]
POST_BUILD = BOARD / 'post-build.sh'

VENDOR_FILES = {
    'ar8030soc/daemon': 'artosyn daemon',
    'ar8030soc/libar8030_client.so': 'artosyn library',
    'usr/lib/libar8030_client.so': 'artosyn library',
    'lib/firmware/bb_config_gnd_pro.json': '{}',
}


class RadioStack(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.d = Path(temp.name)
        # The tree the hook finds its vendor/ in, from its own path.
        root = self.d / 'tree'
        (root / 'br-external/board/ascent-vrx-pro').mkdir(parents=True)
        shutil.copy(POST_BUILD, root / 'br-external/board/ascent-vrx-pro/post-build.sh')
        for rel, data in VENDOR_FILES.items():
            (root / 'vendor/rootfs' / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / 'vendor/rootfs' / rel).write_text(data)
        self.hook = root / 'br-external/board/ascent-vrx-pro/post-build.sh'
        self.target = self.d / 'target'
        (self.target / 'etc').mkdir(parents=True)
        # external.mk's finalize hook, before post-build.sh
        (self.target / 'etc/fpvos-version').write_text('2026.11+g304b4c79\n')
        (self.target / 'usr/lib').mkdir(parents=True)
        (self.target / 'usr/lib/libar8030_client.so').write_text("ar-libre's library")
        for d in ('build', 'host', 'tmp'):
            (self.d / d).mkdir()
        self.config = self.d / '.config'

    def run_hook(self, ar_libre, module=None):
        self.config.write_text('BR2_PACKAGE_MESA3D=y\n' +
                               ('BR2_PACKAGE_AR_LIBRE=y\n' if ar_libre else '# BR2_PACKAGE_AR_LIBRE is not set\n'))
        if module:
            (self.target / module).parent.mkdir(parents=True, exist_ok=True)
            (self.target / module).write_bytes(b'vermagic=6.12.69 SMP\0')
        env = dict(os.environ, BR2_CONFIG=str(self.config), BUILD_DIR=str(self.d / 'build'),
                   HOST_DIR=str(self.d / 'host'), TMPDIR=str(self.d / 'tmp'))
        return subprocess.run(['sh', str(self.hook), str(self.target)], env=env,
                              capture_output=True, text=True)

    def shipped(self, rel):
        p = self.target / rel
        return p.read_text() if p.exists() else None

    def assertOpenRadio(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsNone(self.shipped('ar8030soc/daemon'))
        self.assertIsNone(self.shipped('ar8030soc/libar8030_client.so'))
        self.assertEqual(self.shipped('usr/lib/libar8030_client.so'), "ar-libre's library")
        self.assertEqual(self.shipped('lib/firmware/bb_config_gnd_pro.json'), '{}')

    def test_ar_libre_where_kbuild_puts_it(self):
        self.assertOpenRadio(self.run_hook(True, 'lib/modules/6.12.69/updates/arlink.ko'))

    def test_ar_libre_installed_deeper(self):
        self.assertOpenRadio(self.run_hook(True, 'lib/modules/6.12.69/extra/drivers/net/arlink.ko'))

    def test_ar_libre_compressed(self):
        self.assertOpenRadio(self.run_hook(True, 'lib/modules/6.12.69/updates/arlink.ko.xz'))

    def test_ar_libre_without_its_module_fails_the_build(self):
        (self.target / 'lib/modules/6.12.69').mkdir(parents=True)
        r = self.run_hook(True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('no arlink.ko', r.stderr)
        self.assertEqual(self.shipped('usr/lib/libar8030_client.so'), "ar-libre's library")

    def test_without_ar_libre_the_stock_stack_is_merged(self):
        r = self.run_hook(False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.shipped('ar8030soc/daemon'), 'artosyn daemon')
        self.assertEqual(self.shipped('usr/lib/libar8030_client.so'), 'artosyn library')

    def test_no_configuration_is_an_error(self):
        self.config.unlink(missing_ok=True)
        env = dict(os.environ, BUILD_DIR=str(self.d / 'build'), TMPDIR=str(self.d / 'tmp'))
        env.pop('BR2_CONFIG', None)
        r = subprocess.run(['sh', str(self.hook), str(self.target)], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.shipped('usr/lib/libar8030_client.so'), "ar-libre's library")


if __name__ == '__main__':
    unittest.main()
