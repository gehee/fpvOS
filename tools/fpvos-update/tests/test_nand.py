# SPDX-License-Identifier: GPL-2.0-or-later
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import zlib
from test_update import ROOT, SRC, compile_framework
import test_update


class NandTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.bin = Path(cls.build.name)
        compile_framework(cls.bin)
        (cls.bin/'verify').rename(cls.bin/'verify-real')
        (cls.bin/'verify').write_text(f'#!/bin/sh\necho verify >> verify-calls\nexec "{cls.bin}/verify-real" "$@"\n')
        (cls.bin/'verify').chmod(0o755)
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', '-DWORK="work"', '-DROOT_IMAGES="root"', '-I'+str(SRC),
                        f'-DVERIFY_PROGRAM="{cls.bin / "verify"}"', str(Path(__file__).with_name('nand_sim.c')),
                        '-Wl,--wrap=ioctl', '-Wl,--wrap=pwrite', '-Wl,--wrap=pread', '-o', str(cls.bin / 'sim')], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.package = self.dir / 'bundle'
        self.package.write_bytes(test_update.Tests.fixture(SimpleNamespace(dir=self.dir)))
        for i, size in enumerate((0xb40000, 0x600000, 0x60000, 0x1500000)):
            (self.dir / f'part{i}').write_bytes(bytes([0x30 + i]) * size)
        self.before = self.hashes()

    def tearDown(self):
        self.temp.cleanup()

    def hashes(self):
        return [hashlib.sha256((self.dir / f'part{i}').read_bytes()).hexdigest() for i in range(4)]

    def run_sim(self, mode, check=True):
        return subprocess.run([str(self.bin / 'sim'), mode, str(self.package)], cwd=self.dir,
                              capture_output=True, check=check)

    def test_success_and_readback(self):
        self.run_sim('install')
        self.assertEqual((self.dir/'verify-calls').read_text(), 'verify\n')
        self.assertEqual(self.hashes()[0], self.before[0])
        for i, name in ((1, 'kernel.img'), (2, 'ascent-gnd485.dtb')):
            expected = (self.dir / 'images' / name).read_bytes()
            actual = (self.dir / f'part{i}').read_bytes()
            self.assertEqual(actual[:len(expected)], expected)
            self.assertEqual(set(actual[len(expected):]), {255})
        actual = (self.dir / 'part3').read_bytes()[0x40000:]
        self.assertEqual(actual[:self.package.stat().st_size], self.package.read_bytes())
        self.assertIn('100 4', (self.dir / 'work/status').read_text())

    def test_faults_restore_all_affected_bytes(self):
        for part in (3, 2, 1):
            with self.subTest(part=part):
                self.run_sim(f'fail{part}')
                self.assertEqual(self.hashes(), self.before)
                self.assertIn('previous affected regions restored', (self.dir / 'work/status').read_text())

    def test_torn_control_preserves_previous_record(self):
        self.run_sim('control')
        self.assertEqual(self.hashes()[:3], self.before[:3])

    def test_legacy_fixed_bank_bundle_is_refused_on_stock_bank_one_before_erasing(self):
        result = self.run_sim('legacy-bank1')
        self.assertIn(b'requires a bank-aware', result.stderr)
        self.assertEqual(self.hashes(), self.before)

    def test_staging_mutation_after_verification_cannot_change_programmed_bytes(self):
        original = self.package.read_bytes()
        for mode in ('mutate1', 'mutate2', 'mutate3'):  # unlink, replace, same-inode write
            with self.subTest(mode=mode):
                self.package.write_bytes(original)
                self.run_sim(mode)
                actual = (self.dir / 'part3').read_bytes()[0x40000:0x40000+len(original)]
                self.assertEqual(actual, original)
                self.assertEqual(self.hashes()[0], self.before[0])
                self.assertIn('100 4', (self.dir / 'work/status').read_text())

    def test_invalid_snapshot_refuses_install_without_erasing(self):
        damaged = bytearray(self.package.read_bytes()); damaged[-1] ^= 1
        self.package.write_bytes(damaged)
        self.run_sim('invalid')
        self.assertEqual(self.hashes(), self.before)
        self.assertEqual(list((self.dir/'work').glob('install.*')), [])

    def test_bad_block_in_any_write_range_refuses_before_first_erase(self):
        for part in (1, 2, 3):
            with self.subTest(part=part):
                self.run_sim(f'bad{part}')
                self.assertEqual(self.hashes(), self.before)

    def vendor_restore_fixture(self):
        kernel = bytearray((self.dir / 'images/kernel.img').read_bytes())
        struct.pack_into('<I', kernel, 12, 0x200a0000)
        struct.pack_into('>II', kernel, 80, 0x200a0000, 0x200a0000)
        struct.pack_into('>I', kernel, 68, 0)
        struct.pack_into('>I', kernel, 68, zlib.crc32(kernel[64:128]))
        struct.pack_into('<I', kernel, 32, sum(kernel[64:]))
        kernel += b'Z' * (0x600000-len(kernel))
        dtb = (self.dir / 'images/ascent-gnd485.dtb').read_bytes()
        dtb += b'Y' * (0x60000-len(dtb))
        (self.dir / 'kernel.before.bin').write_bytes(kernel)
        (self.dir / 'dtb.before.bin').write_bytes(dtb)
        self.package.write_bytes(test_update.PACKAGE.build(self.dir, test_update.BOARD, vendor_restore=True))
        return kernel, dtb

    def test_vendor_restore_leaves_entire_inactive_bank_unchanged(self):
        kernel, dtb = self.vendor_restore_fixture()
        for runtime in ('stock0', 'stock1', 'native'):
            for region in ('control', 'tail'):
                with self.subTest(runtime=runtime, bad_region=region):
                    self.run_sim(f'restore-{runtime}-{region}')
                    self.assertEqual((self.dir / 'part1').read_bytes(), kernel)
                    self.assertEqual((self.dir / 'part2').read_bytes(), dtb)
                    self.assertEqual(self.hashes()[0], self.before[0])
                    self.assertEqual(self.hashes()[3], self.before[3])

    def test_vendor_restore_bad_kernel_or_dtb_refuses_before_erasing(self):
        self.vendor_restore_fixture()
        for part in (1, 2):
            with self.subTest(part=part):
                self.run_sim(f'restore-bad{part}')
                self.assertEqual(self.hashes(), self.before)

    def test_layout_crc_and_active_bank(self):
        raw = bytearray(b'\xff' * 0xb40000)
        entries = bytearray(16384)
        for i, (name, start, size) in enumerate((('kernel', 0xb40000, 0x600000), ('dtb', 0x1140000, 0x60000),
                                                ('userapp0', 0x11a0000, 0x1500000), ('userapp1', 0x26a0000, 0x1500000))):
            struct.pack_into('<QQQ', entries, i*128+32, start//512, (start+size)//512-1, (1<<47) if i != 3 else 0)
            entries[i*128+56:i*128+56+len(name)*2] = name.encode('utf-16le')
        def save():
            h = bytearray(512); h[:8] = b'EFI PART'
            struct.pack_into('<II', h, 8, 0x10000, 92)
            struct.pack_into('<QQQQ', h, 24, 1, 0x3f7ff, 0xc00, 0x3f7de)
            struct.pack_into('<QIII', h, 72, 2, 128, 128, zlib.crc32(entries))
            struct.pack_into('<I', h, 16, zlib.crc32(h[:92]))
            raw[0x100200:0x100400] = h
            raw[0x100400:0x104400] = entries
            (self.dir / 'part0').write_bytes(raw)
        save(); self.run_sim('layout')
        entries[3*128+53] ^= 0x80  # active flag, with otherwise valid CRCs
        save(); self.assertNotEqual(self.run_sim('layout', False).returncode, 0)
        entries[3*128+53] ^= 0x80
        save(); raw[0x100210] ^= 1
        (self.dir / 'part0').write_bytes(raw)
        self.assertNotEqual(self.run_sim('layout', False).returncode, 0)

    def test_redundant_gpt_generation_and_protected_stock_selection(self):
        self.test_layout_crc_and_active_bank()
        raw = bytearray((self.dir / 'part0').read_bytes())
        # Repair the intentionally corrupted primary header from the prior test.
        raw[0x100210] ^= 1
        first = bytes(raw[0x100000:0x104400])

        def save(first_gen, second_gen, first_root=0, second_root=0):
            for slot, generation, root in ((0, first_gen, first_root), (1, second_gen, second_root)):
                g = bytearray(first)
                struct.pack_into('<I', g, 532, generation)
                struct.pack_into('<QQ', g, 536, 0x3f7ff if slot else 1, 1 if slot else 0x3f7ff)
                struct.pack_into('<Q', g, 584, 0x3f7df if slot else 2)
                for i in (2, 3):
                    struct.pack_into('<Q', g, 1024+i*128+48, (1<<47) if i == 2+root else 0)
                struct.pack_into('<I', g, 600, zlib.crc32(g[1024:17408]))
                struct.pack_into('<I', g, 528, 0)
                struct.pack_into('<I', g, 528, zlib.crc32(g[512:604]))
                raw[0x100000+slot*0x40000:0x104400+slot*0x40000] = g
            (self.dir / 'part0').write_bytes(raw)

        # Migration: newer primary selects stock, older secondary selects fpvOS.
        save(11, 10, 0, 1)
        before = self.hashes()
        self.run_sim('layout')
        self.assertEqual(self.hashes(), before)
        # Either stock bank is valid; equal-generation conflicting tables are not.
        save(11, 12, 1, 0); self.run_sim('layout')
        for generations in ((11, 10, 1, 0), (11, 12, 0, 1)):
            save(*generations)
            self.run_sim('layout')
        save(11, 11, 0, 1)
        self.assertNotEqual(self.run_sim('layout', False).returncode, 0)
        save(11, 11); self.run_sim('layout')
        raw[0x140210] ^= 1
        (self.dir / 'part0').write_bytes(raw)
        self.assertNotEqual(self.run_sim('layout', False).returncode, 0)
