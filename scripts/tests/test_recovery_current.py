#!/usr/bin/env python3
"""boot/recovery-current.sh: an image whose kernel carries another recovery
root than the image's own - version, updater, update helper - or one built
after the kernel was linked, is refused at the post-image step."""
from pathlib import Path
import os
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'boot/recovery-current.sh'

# An objcopy stand-in: a stand-in executable's "code" is its bytes less the
# line that says how it was stripped (the two real copies are stripped apart).
OBJCOPY = '''#!/bin/sh
in= out=
for a; do in=$out; out=$a; done
grep -v '^strip:' "$in" > "$out"
'''


class RecoveryCurrent(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        d = Path(temp.name)
        self.build, self.target, self.host = d / 'build', d / 'target', d / 'host'
        self.root = self.build / 'fpvos-recovery-1/root'
        for base, strip in ((self.root, 'unneeded'), (self.target, 'all')):
            for sub in ('etc', 'usr/sbin', 'usr/libexec'):
                (base / sub).mkdir(parents=True)
            (base / 'etc/fpvos-version').write_text('2026.11.beta1+g1234abcd\n')
            (base / 'usr/sbin/fpvos-update').write_text(f'strip: {strip}\nthe updater\n')
            (base / 'usr/libexec/fpvos-update-backend').write_text('#!/bin/sh\n')
        (self.host / 'bin').mkdir(parents=True)
        objcopy = self.host / 'bin/aarch64-test-objcopy'
        objcopy.write_text(OBJCOPY); objcopy.chmod(0o755)
        self.packed = self.build / 'linux-custom/usr/initramfs_data.cpio'
        self.packed.parent.mkdir(parents=True)
        self.packed.write_bytes(b'cpio')
        later = time.time() + 60
        os.utime(self.packed, (later, later))

    def check(self):
        env = dict(os.environ, BUILD_DIR=str(self.build), TARGET_DIR=str(self.target), HOST_DIR=str(self.host))
        r = subprocess.run(['sh', str(SCRIPT)], env=env, capture_output=True, text=True)
        self.assertEqual([p.name for p in self.build.iterdir() if p.name.startswith('.recovery-current')], [])
        return r

    def test_the_image_own_recovery_root(self):
        """Stripped differently, the same code: current."""
        r = self.check()
        self.assertEqual((r.returncode, r.stderr), (0, ''))

    def test_another_version(self):
        (self.root / 'etc/fpvos-version').write_text('2026.11.beta1\n')
        r = self.check()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('says 2026.11.beta1, the image 2026.11.beta1+g1234abcd', r.stderr)
        self.assertIn('make fpvos-recovery-rebuild all', r.stderr)

    def test_another_updater(self):
        (self.root / 'usr/sbin/fpvos-update').write_text('strip: unneeded\nan older updater\n')
        r = self.check()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('another updater', r.stderr)

    def test_another_helper(self):
        (self.root / 'usr/libexec/fpvos-update-backend').write_text('#!/bin/sh\n# older\n')
        r = self.check()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('another update helper', r.stderr)

    def test_built_after_the_kernel(self):
        """The root is right, the kernel was linked before it was."""
        for name in ('usr/sbin/fpvos-update', 'etc/fpvos-version'):
            with self.subTest(name):
                later = time.time() + 600
                os.utime(self.root / name, (later, later))
                r = self.check()
                self.assertNotEqual(r.returncode, 0)
                self.assertIn('built after the kernel', r.stderr)
                now = time.time()
                os.utime(self.root / name, (now, now))

    def test_no_kernel_build(self):
        self.packed.unlink()
        r = self.check()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('no kernel build', r.stderr)


if __name__ == '__main__':
    unittest.main()
