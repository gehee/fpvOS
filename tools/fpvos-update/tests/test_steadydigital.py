# SPDX-License-Identifier: GPL-2.0-or-later
"""SteadyDigital install: what is checked before bank B is touched, and the order after."""
from pathlib import Path
import hashlib
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from test_update import ROOT, SRC

sys.path.insert(0, str(ROOT / 'tools/fpvos-update'))
import package  # noqa: E402

BACKEND = ROOT / 'br-external/package/fpvos-update/backends/skyzone-steadydigital'
# The simulator's board: the real names and limits, board id 0.
BOARD = {'board_id': 0, 'names': ['kernel.img', 'skyzone-steadydigital.dtb', 'rootfs.squashfs'],
         'limits': [6291456, 65536, 25165824], 'counts': [3, 0], 'bundle_limits': [33554432, 512]}


def squashfs(size=8192):
    root = bytearray(size)
    root[:4] = b'hsqs'
    struct.pack_into('<IIHHHHHH', root, 12, 131072, 0, 1, 17, 0, 1, 4, 0)
    struct.pack_into('<Q', root, 40, size - 100)
    return bytes(root)


def bundle(directory, dtb=b'D' * 300, root=None):
    images = directory / 'images'
    images.mkdir()
    (images / 'kernel.img').write_bytes(bytes(range(256)) * 40)
    (images / 'skyzone-steadydigital.dtb').write_bytes(dtb)
    (images / 'rootfs.squashfs').write_bytes(root or squashfs())
    return package.build(images, BOARD)


class SteadyDigitalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.build = Path(cls.temp.name)
        common = ['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-ffunction-sections', '-fdata-sections',
                  '-I' + str(SRC), '-I' + str(BACKEND), '-DP1_WORK="work"', '-DP1_ROOT="work/root"']
        renames = ['p1_preflight', 'p1_stock', 'p1_state_mount', 'p1_state_unmount', 'p1_bundle_read',
                   'p1_bundle_write', 'p1_bundle_present', 'p1_active_bank', 'p1_mtd', 'p1_gpt_read',
                   'p1_bundle_open', 'p1_root_attach']
        subprocess.run(common + ['-D' + s + '=unused_' + s for s in renames] +
                       ['-c', str(BACKEND / 'storage.c'), '-o', str(cls.build / 'storage.o')], check=True)
        subprocess.run(common + [str(Path(__file__).with_name('sd_transaction_sim.c')), str(cls.build / 'storage.o'),
                                 str(SRC / 'bootstrap-common.c'), '-Wl,--gc-sections', '-Wl,--wrap=execlp',
                                 '-Wl,--wrap=lstat', '-o', str(cls.build / 'transaction')], check=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def transaction(self, mode, prepare=None):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); d = Path(temp.name)
        (d / 'work/state').mkdir(parents=True, mode=0o700)
        (d / 'volume').write_bytes(b'previous volume')
        (d / 'upload').write_bytes(b'v' * 600)
        if prepare:
            prepare(d)
        r = subprocess.run([str(self.build / 'transaction'), mode], cwd=d, capture_output=True)
        events = (d / 'events').read_text().splitlines() if (d / 'events').exists() else []
        return d, r, events

    def test_bank_b_is_checked_before_anything_is_selected_or_written(self):
        d, r, events = self.transaction('ok')
        self.assertEqual(r.returncode, 0, r.stderr)
        order = ['verify', 'active-bank', 'bundle-present', 'select-stock', 'kernel', 'dtb', 'write', 'readback', 'activate']
        self.assertEqual([e for e in events if e in order], order)
        self.assertEqual((d / 'volume').read_bytes(), b'v' * 600)

    def test_live_stock_in_bank_b_and_an_unusable_volume_change_nothing(self):
        for fault, said in (('stock-b', b"unit's stock"), ('bad-volume', b'cannot be used'), ('gpt', b'')):
            with self.subTest(fault=fault):
                d, r, events = self.transaction(fault)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(said, r.stderr)
                for touched in ('mount', 'select-stock', 'kernel', 'dtb', 'write', 'activate'):
                    self.assertNotIn(touched, events)
                self.assertEqual((d / 'volume').read_bytes(), b'previous volume')

    def test_an_install_records_the_bundle_it_wrote(self):
        d, r, events = self.transaction('ok')
        self.assertEqual(r.returncode, 0, r.stderr)
        upload = b'v' * 600
        crc = struct.unpack_from('<I', upload, 508)[0]
        self.assertEqual((d / 'work/state/fpvos-installed').read_text(),
                         f'{hashlib.sha256(upload).hexdigest()} {crc:08x}\n')
        self.assertLess(events.index('readback'), events.index('activate'))
        self.assertNotIn('gzip', events)

    def installed(self, data, record=True, crc_delta=0):
        def prepare(d):
            (d / 'volume').write_bytes(data)
            if record:
                crc = (struct.unpack_from('<I', data, 508)[0] + crc_delta) & 0xffffffff
                (d / 'work/state/fpvos-installed').write_text(f'{hashlib.sha256(data).hexdigest()} {crc:08x}\n')
        return prepare

    def test_a_boot_mounts_the_installed_root_where_it_lies(self):
        with tempfile.TemporaryDirectory() as temp:
            data = bundle(Path(temp))
        d, r, events = self.transaction('boot', self.installed(data))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([e for e in events if e.startswith('compare')], ['compare-kernel', 'compare-dtb'])
        self.assertNotIn('readback', events)
        self.assertNotIn('verify', events)
        offset = 512 + 10240 + 300
        self.assertEqual((d / 'attached').read_text(), f'{offset} 8192\n')
        self.assertEqual(os.readlink(d / 'work/root/rootfs.squashfs'), '/dev/loop7')
        self.assertEqual((d / 'work/root/installed-sha256').read_text(), hashlib.sha256(data).hexdigest() + '\n')
        self.assertFalse((d / 'work/root/kernel-head').exists())

    def test_a_boot_refuses_anything_but_the_installed_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            good = bundle(Path(temp))
        with tempfile.TemporaryDirectory() as temp:
            bad_root = bundle(Path(temp), root=b'x' * 8192)
        torn_dtb = bytearray(good); torn_dtb[512 + 10240] ^= 1
        torn_header = bytearray(good); torn_header[100] ^= 1
        cases = {'no record': self.installed(good, record=False),
                 'another bundle': self.installed(good, crc_delta=1),
                 'header': self.installed(bytes(torn_header)),
                 'dtb': self.installed(bytes(torn_dtb)),
                 'root': self.installed(bad_root)}
        for name, prepare in cases.items():
            with self.subTest(case=name):
                d, r, events = self.transaction('boot', prepare)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertNotIn('attach', events)
                self.assertFalse((d / 'work/root/installed-sha256').exists())
        # The volume is larger than the bundle, as on UBI; one too small fails.
        d, r, events = self.transaction('boot-small', self.installed(good[:-1]))
        self.assertEqual(r.returncode, 1)
        self.assertNotIn('attach', events)
        d, r, events = self.transaction('boot-attach', self.installed(good))
        self.assertEqual(r.returncode, 1)
        self.assertFalse((d / 'work/root/rootfs.squashfs').exists())

    def test_a_clean_request_wins_over_the_installed_root(self):
        def prepare(d):
            self.installed(bundle(d))(d)
            (d / 'work/state/fpvos-update-clean').write_text('1\n')
        d, r, events = self.transaction('boot', prepare)
        self.assertEqual(r.returncode, 10, r.stderr)
        self.assertNotIn('open', events)
        self.assertFalse((d / 'work/state/fpvos-update-clean').exists())

    def test_stock_in_bank_a_leaves_bank_b_free_whatever_it_holds(self):
        d, r, events = self.transaction('stock-a')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('activate', events)

    def test_faults_after_the_checks_never_select_bank_b(self):
        for fault in ('verify', 'select-stock', 'kernel', 'dtb', 'write', 'readback', 'corrupt'):
            with self.subTest(fault=fault):
                d, r, events = self.transaction(fault)
                self.assertNotEqual(r.returncode, 0)
                self.assertNotIn('activate', events)
                if fault in ('verify', 'select-stock', 'kernel', 'dtb'):
                    self.assertNotIn('write', events)
                    self.assertEqual((d / 'volume').read_bytes(), b'previous volume')


if __name__ == '__main__':
    unittest.main()
