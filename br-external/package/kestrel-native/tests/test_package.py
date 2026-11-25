#!/usr/bin/env python3
"""kestrel-native.mk's install step with Buildroot's variables stubbed: the
runtime image is checked against its board's pin in runtime.hash, or
KESTREL_NATIVE_SHA256 when that is set (empty: none), and its sha256 is
always recorded in the image."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]

MAKEFILE = '''generic-package =
INSTALL = install
TARGET_DIR = $(CURDIR)/target
KESTREL_NATIVE_PKGDIR = {pkgdir}
include $(KESTREL_NATIVE_PKGDIR)/kestrel-native.mk
@D = $(CURDIR)
install:
\t$(KESTREL_NATIVE_INSTALL_TARGET_CMDS)
'''


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('make') and shutil.which('sha256sum'),
                     'Buildroot host tools: GNU make, install -D, sha256sum')
class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'Makefile').write_text(MAKEFILE.format(pkgdir=PACKAGE))
        (self.root/'kestrel-gnd-supervise').write_text('')
        self.image = self.root/'runtime.squashfs'
        self.image.write_bytes(b'hsqs runtime stand-in\n')
        self.sum = hashlib.sha256(self.image.read_bytes()).hexdigest()
        self.target = self.root/'target/usr/share/kestrel'

    def install(self, *args, **env):
        environment = {k: v for k, v in os.environ.items() if not k.startswith('KESTREL_NATIVE_')}
        return subprocess.run(['make', '-s', '-C', str(self.root), 'install',
                               f'KESTREL_NATIVE_IMAGE={self.image}', *args],
                              capture_output=True, text=True, env={**environment, **env})

    def pin(self, board):
        for line in (PACKAGE/'runtime.hash').read_text().splitlines():
            if line.split()[:1] == [board]:
                return line.split()[1]
        raise AssertionError(f'no {board} line in runtime.hash')

    def test_unpinned_image_records_its_sha256(self):
        """KESTREL_NATIVE_SHA256= (empty): a runtime of your own, no pin."""
        r = self.install('KESTREL_NATIVE_SHA256=')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.target/'runtime.squashfs').read_bytes(), self.image.read_bytes())
        self.assertEqual((self.target/'runtime.sha256').read_text(), f'{self.sum}  runtime.squashfs\n')

    def test_matching_pin_installs(self):
        r = self.install(f'KESTREL_NATIVE_SHA256={self.sum.upper()}')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.target/'runtime.sha256').read_text(), f'{self.sum}  runtime.squashfs\n')

    def test_default_pin_is_the_boards_in_runtime_hash(self):
        """No KESTREL_NATIVE_SHA256: runtime.hash's pin for the board - the P1
        goggles' own, the ascent one for the others - and any other file is
        refused before anything is installed."""
        for flags, board in (([], 'ascent'), (['BR2_FPVOS_BOARD_P1_GOGGLE=y'], 'p1goggle')):
            with self.subTest(board):
                r = self.install(*flags)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(f'not KESTREL_NATIVE_SHA256 {self.pin(board)}', r.stderr)
                self.assertFalse((self.target/'runtime.squashfs').exists())

    def test_mismatched_pin_fails_before_installing(self):
        r = self.install(KESTREL_NATIVE_SHA256='0' * 64)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('not KESTREL_NATIVE_SHA256', r.stderr)
        self.assertFalse((self.target/'runtime.squashfs').exists())
        self.assertFalse((self.target/'runtime.sha256').exists())


if __name__ == '__main__':
    unittest.main()
