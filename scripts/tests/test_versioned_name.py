#!/usr/bin/env python3
"""boot/versioned-name.sh: a built image under its release name, the plain
name left as a link to it, earlier versions' copies gone - whether the next
build replaces the link or writes through it."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'boot/versioned-name.sh'


class VersionedName(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.d = Path(temp.name)

    def name(self, *args, ok=True):
        r = subprocess.run(['sh', str(SCRIPT), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(r.returncode == 0, ok, r.stderr)
        return r.stdout.strip()

    def test_renamed_and_linked(self):
        f = self.d / 'fpvos-p1-air.fwu'
        f.write_bytes(b'one')
        out = self.name(f, '2026.11.beta1')
        self.assertEqual(out, str(self.d / 'fpvos-p1-air-2026.11.beta1.fwu'))
        self.assertTrue(f.is_symlink())
        self.assertEqual(os.readlink(f), 'fpvos-p1-air-2026.11.beta1.fwu')
        self.assertEqual(f.read_bytes(), b'one')

    def test_next_build_replaces_the_link(self):
        """The packager replaces the link with a new file (os.replace)."""
        f = self.d / 'fpvos-p1-air.fwu'
        f.write_bytes(b'one')
        self.name(f, '2026.11.beta1')
        f.unlink()
        f.write_bytes(b'two')
        self.name(f, '2026.11.beta1+g1234abcd')
        self.assertEqual(sorted(p.name for p in self.d.iterdir()),
                         ['fpvos-p1-air-2026.11.beta1+g1234abcd.fwu', 'fpvos-p1-air.fwu'])
        self.assertEqual(f.read_bytes(), b'two')

    def test_next_build_writes_through_the_link(self):
        """A tool that opens the plain name writes the previous version's
        file: it becomes the new version's, under its new name."""
        f = self.d / 'kernel-recovery.img'
        f.write_bytes(b'one')
        self.name(f, '2026.11.beta1', 'fpvos-p1-air-recovery')
        f.write_bytes(b'two')
        self.name(f, '2026.12.beta1', 'fpvos-p1-air-recovery')
        self.assertEqual(sorted(p.name for p in self.d.iterdir()),
                         ['fpvos-p1-air-recovery-2026.12.beta1.img', 'kernel-recovery.img'])
        self.assertEqual(f.read_bytes(), b'two')

    def test_same_version_again(self):
        f = self.d / 'fpvos-p1-air.fwu'
        f.write_bytes(b'one')
        self.name(f, '2026.11.beta1')
        self.name(f, '2026.11.beta1')
        self.assertEqual(f.read_bytes(), b'one')
        self.assertEqual(len(list(self.d.iterdir())), 2)

    def test_card_image(self):
        f = self.d / 'sdcard.img.xz'
        f.write_bytes(b'xz')
        self.assertEqual(self.name(f, '2026.11.beta1', 'fpvos-vrxpro'), str(self.d / 'fpvos-vrxpro-2026.11.beta1.img.xz'))
        self.assertEqual(os.readlink(f), 'fpvos-vrxpro-2026.11.beta1.img.xz')

    def test_other_files_left_alone(self):
        """Only earlier versions of this name go: not another board's file
        whose name starts the same, nor one of another kind."""
        keep = ['fpvos-steadydigital-recovery-2026.11.beta1.img', 'fpvos-steadydigital-notes.fwu',
                'fpvos-steadydigital-2026.11.beta1.txt']
        for k in keep:
            (self.d / k).write_bytes(b'keep')
        f = self.d / 'fpvos-steadydigital.fwu'
        f.write_bytes(b'one')
        self.name(f, '2026.11.beta1')
        for k in keep:
            self.assertTrue((self.d / k).exists(), k)

    def test_refused(self):
        f = self.d / 'fpvos-p1-air.fwu'
        self.name(f, '2026.11.beta1', ok=False)          # no such file
        f.write_bytes(b'one')
        for bad in ('', 'a/b', 'a b'):
            self.name(f, bad, ok=False)
        self.assertFalse(f.is_symlink())


if __name__ == '__main__':
    unittest.main()
