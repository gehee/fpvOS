#!/usr/bin/env python3
"""boot/mk-sd-image.sh refuses a piece that does not fit where it is written,
against the layout the script itself defines, and leaves neither temporary
files nor a half-written image behind when it fails."""
from pathlib import Path
import hashlib
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / 'boot/mk-sd-image.sh'
TEXT = SCRIPT.read_text()
SIZES = {k: int(v) for k, v in re.findall(r'\b(\w+_SIZE|IMG_MB)=(\d+)', TEXT)}
P1_OVERHEAD = eval(re.search(r'^P1_OVERHEAD=\$\(\((.*)\)\)$', TEXT, re.M).group(1))

# mtools and sfdisk stood in for, logging; mcopy fails with FAIL_MCOPY set.
# truncate too, for macOS, which has none.
STANDINS = {
    'sfdisk': '#!/bin/sh\ncat > /dev/null\necho "sfdisk $*" >> "$T/calls"\n',
    'mformat': '#!/bin/sh\necho "mformat $*" >> "$T/calls"\n',
    'mmd': '#!/bin/sh\necho "mmd $*" >> "$T/calls"\n',
    'mcopy': '#!/bin/sh\necho "mcopy $*" >> "$T/calls"\n[ -z "$FAIL_MCOPY" ]\n',
    'xz': '#!/bin/sh\necho "xz $*" >> "$T/calls"\n',
    'sha256sum': '#!/usr/bin/env python3\nimport hashlib, sys\n'
                 'print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest() + "  " + sys.argv[1])\n',
    'truncate': '#!/usr/bin/env python3\nimport sys\n'
                'n = sys.argv[2]; m = {"M": 1 << 20}.get(n[-1], 1)\n'
                'open(sys.argv[3], "ab").truncate(int(n.rstrip("M")) * m)\n',
}


class Image(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.d = Path(temp.name)
        for sub in ('bin', 'images', 'tmp'):
            (self.d / sub).mkdir()
        for name, text in STANDINS.items():
            p = self.d / 'bin' / name; p.write_text(text); p.chmod(0o755)
        self.out = self.d / 'sdcard.img'
        for name, size in (('uboot-patched.bin', 4096), ('boot-sd3.img', 8192), ('Image', 65536),
                           ('rk3568-pro-patched.dtb', 1024), ('rootfs.ext2', 1 << 20)):
            self.piece(name, size)

    def piece(self, name, size):
        with open(self.d / 'images' / name, 'wb') as f:      # sparse
            f.truncate(size)
        if name == 'Image':   # the boot chain, rebuilt with it: the FIT boots this kernel
            self.fit_kernel(self.d / 'images' / 'Image')

    def fit_kernel(self, image):
        digest = hashlib.sha256(Path(image).read_bytes()).hexdigest()
        (self.d / 'images' / 'boot-sd3.img.kernel-sha256').write_text(digest + '\n')

    def build(self, **env):
        e = dict(os.environ, PATH=f'{self.d}/bin:/usr/bin:/bin', T=str(self.d), TMPDIR=str(self.d / 'tmp'),
                 BR_IMAGES=str(self.d / 'images'), OUT=str(self.out), COMPRESS='0', **env)
        r = subprocess.run(['bash', str(SCRIPT)], env=e, capture_output=True, text=True)
        self.err = r.stderr
        self.assertEqual(list((self.d / 'tmp').iterdir()), [], 'temporary files left behind')
        return r.returncode

    def assertRefused(self, what):
        self.assertNotEqual(self.build(), 0)
        self.assertIn(f'TOO BIG: {what}', self.err)
        self.assertFalse(self.out.exists())

    def test_pieces_that_fit_make_an_image(self):
        self.assertEqual(self.build(), 0, self.err)
        self.assertEqual(self.out.stat().st_size, SIZES['IMG_MB'] << 20)

    def test_a_piece_exactly_its_partitions_size_fits(self):
        self.piece('boot-sd3.img', SIZES['P3_SIZE'] * 512)
        self.piece('uboot-patched.bin', SIZES['LOADER_SIZE'] * 512)
        self.assertEqual(self.build(), 0, self.err)

    def test_a_fit_booting_another_kernel_is_refused(self):
        # The kernel rebuilt, the boot chain not: the FIT boots the old one.
        with open(self.d / 'images' / 'Image', 'r+b') as f:
            f.write(b'a newer kernel')
        self.assertNotEqual(self.build(), 0)
        self.assertIn('boots another kernel than images/Image', self.err)
        self.assertFalse(self.out.exists())
        self.assertNotIn('sfdisk', (self.d / 'calls').read_text() if (self.d / 'calls').exists() else '')

    def test_rootfs_larger_than_p2(self):
        self.piece('rootfs.ext2', SIZES['P2_SIZE'] * 512 + 1)
        self.assertRefused('rootfs.ext2')

    def test_fit_larger_than_p3(self):
        self.piece('boot-sd3.img', SIZES['P3_SIZE'] * 512 + 1)
        self.assertRefused('boot-sd3.img')

    def test_loader_larger_than_its_area(self):
        self.piece('uboot-patched.bin', SIZES['LOADER_SIZE'] * 512 + 1)
        self.assertRefused('uboot-patched.bin')

    def test_kernel_and_dtb_larger_than_p1(self):
        self.piece('Image', SIZES['P1_SIZE'] * 512 - P1_OVERHEAD)
        self.assertRefused('Image + rk3568-pro.dtb')

    def test_a_failure_halfway_cleans_up(self):
        self.out.write_text('an image from an earlier build')
        self.assertNotEqual(self.build(FAIL_MCOPY='1'), 0)
        self.assertFalse(self.out.exists())


if __name__ == '__main__':
    unittest.main()
