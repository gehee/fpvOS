# SPDX-License-Identifier: GPL-2.0-or-later
"""SteadyDigital install: which bank it writes, what is checked before that bank is
touched, and the order after; a boot reads the root of the bank SPL booted."""
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
from test_p1 import TARGETS, REFUSALS, STOCK_BANKS, every_scenario, booted_stock, stock_banks, written_to

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

    def transaction(self, mode, prepare=None, banks='r1sf'):
        """MODE: an install fault, "boot..." or "stock". BANKS: what runs, the
        booted bank, then what bank 0 and bank 1 hold (sd_transaction_sim.c)."""
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); d = Path(temp.name)
        (d / 'work/state').mkdir(parents=True, mode=0o700)
        for bank in (0, 1): (d / f'volume{bank}').write_bytes(b'previous volume %d' % bank)
        (d / 'upload').write_bytes(b'v' * 600)
        if prepare:
            prepare(d)
        r = subprocess.run([str(self.build / 'transaction'), mode, banks], cwd=d, capture_output=True)
        events = (d / 'events').read_text().splitlines() if (d / 'events').exists() else []
        return d, r, events

    def test_both_banks_are_checked_before_anything_is_selected_or_written(self):
        d, r, events = self.transaction('ok')
        self.assertEqual(r.returncode, 0, r.stderr)
        order = ['verify', 'active-bank', 'bundle-present', 'bundle-present', 'select-stock', 'kernel', 'dtb',
                 'write', 'readback', 'activate']
        self.assertEqual([e for e in events if e in order], order)
        self.assertEqual((d / 'volume1').read_bytes(), b'v' * 600)

    # Scenario -> the bank written, as for the P1 (test_p1.py).
    TARGETS = TARGETS

    def test_the_target_bank_is_chosen_from_what_each_bank_holds(self):
        for banks, target in self.TARGETS.items():
            with self.subTest(banks=banks):
                d, r, events = self.transaction('ok', banks=banks)
                self.assertEqual(r.returncode, 0, r.stderr)
                for written in ('kernel', 'dtb', 'write', 'readback', 'activate'):
                    self.assertIn(f'{written}@{target}', events)
                self.assertIn(f'select-stock@{1 - target}', events)
                self.assertEqual((d / f'volume{target}').read_bytes(), b'v' * 600)
                self.assertEqual((d / f'volume{1 - target}').read_bytes(), b'previous volume %d' % (1 - target))

    def test_booted_stock_is_never_written(self):
        for banks, target in self.TARGETS.items():
            if not booted_stock(banks):
                continue
            with self.subTest(banks=banks):
                d, r, events = self.transaction('ok', banks=banks)
                self.assertNotEqual(target, int(banks[1]))
                self.assertFalse(written_to(events, int(banks[1])))

    def test_refusals_change_nothing(self):
        for (fault, banks), said in {**REFUSALS, ('gpt', 'r1sf'): b''}.items():
            with self.subTest(fault=fault, banks=banks):
                d, r, events = self.transaction(fault, banks=banks)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(said, r.stderr)
                for touched in ('mount', 'select-stock', 'kernel', 'dtb', 'write', 'activate'):
                    self.assertNotIn(touched, events)
                for bank in (0, 1):
                    self.assertEqual((d / f'volume{bank}').read_bytes(), b'previous volume %d' % bank)

    def test_a_booted_fpvos_whose_root_is_in_use_never_takes_the_stock_bank(self):
        # Normal mode holds the booted bank's bundle as the running root
        # (ubiblock); a recovery after a root that did not mount can too.
        for banks in ('r0us', 'r1su', 'r0ds', 'r1sd'):
            with self.subTest(banks=banks):
                d, r, events = self.transaction('ok', banks=banks)
                stock = 1 - int(banks[1])
                self.assertFalse(written_to(events, stock))
                self.assertEqual((d / f'volume{stock}').read_bytes(), b'previous volume %d' % stock)

    def test_every_case_keeps_a_stock_bank(self):
        for banks in every_scenario():
            with self.subTest(banks=banks):
                d, r, events = self.transaction('ok', banks=banks)
                if r.returncode:
                    for touched in ('mount', 'select-stock', 'kernel', 'dtb', 'write', 'activate'):
                        self.assertNotIn(touched, events)
                    continue
                target = [b for b in (0, 1) if f'write@{b}' in events]
                self.assertEqual(len(target), 1)
                if stock_banks(banks):
                    self.assertIn(1 - target[0], stock_banks(banks))

    def test_stock_selects_the_bank_that_holds_stock(self):
        # 'r0us'/'r1su': normal mode, the root held from the booted bank's
        # volume, the one place the Flasher offers "Switch to stock".
        for banks, expected in STOCK_BANKS.items():
            with self.subTest(banks=banks):
                d, r, events = self.transaction('stock', banks=banks)
                if expected is None:
                    self.assertNotEqual(r.returncode, 0)
                    self.assertIn(b'no stock bank', r.stderr)
                else:
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertEqual(r.stdout.strip(), b'stock bank %d' % expected)

    def test_stock_never_selects_a_bank_without_stock(self):
        for banks in every_scenario():
            with self.subTest(banks=banks):
                d, r, events = self.transaction('stock', banks=banks)
                if r.returncode == 0:
                    self.assertIn(int(r.stdout.split()[-1]), stock_banks(banks))

    def test_an_install_records_the_bundle_it_wrote(self):
        d, r, events = self.transaction('ok')
        self.assertEqual(r.returncode, 0, r.stderr)
        upload = b'v' * 600
        crc = struct.unpack_from('<I', upload, 508)[0]
        self.assertEqual((d / 'work/state/fpvos-installed').read_text(),
                         f'{hashlib.sha256(upload).hexdigest()} {crc:08x}\n')
        self.assertLess(events.index('readback'), events.index('activate'))
        self.assertNotIn('gzip', events)

    def installed(self, data, record=True, crc_delta=0, bank=1):
        def prepare(d):
            (d / f'volume{bank}').write_bytes(data)
            if record:
                crc = (struct.unpack_from('<I', data, 508)[0] + crc_delta) & 0xffffffff
                (d / 'work/state/fpvos-installed').write_text(f'{hashlib.sha256(data).hexdigest()} {crc:08x}\n')
        return prepare

    def test_a_boot_mounts_the_installed_root_where_it_lies(self):
        with tempfile.TemporaryDirectory() as temp:
            data = bundle(Path(temp))
        d, r, events = self.transaction('boot', self.installed(data))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([e for e in events if e.startswith('compare') and '@' not in e], ['compare-kernel', 'compare-dtb'])
        self.assertNotIn('readback', events)
        self.assertNotIn('verify', events)
        offset = 512 + 10240 + 300
        self.assertEqual((d / 'attached').read_text(), f'{offset} 8192\n')
        self.assertEqual(os.readlink(d / 'work/root/rootfs.squashfs'), '/dev/loop7')
        self.assertEqual((d / 'work/root/installed-sha256').read_text(), hashlib.sha256(data).hexdigest() + '\n')
        self.assertFalse((d / 'work/root/kernel-head').exists())

    def test_a_boot_reads_the_root_and_checks_the_kernel_of_the_booted_bank(self):
        for bank in (0, 1):
            with self.subTest(bank=bank):
                with tempfile.TemporaryDirectory() as temp:
                    data = bundle(Path(temp))
                banks = 'r0fs' if bank == 0 else 'r1sf'
                d, r, events = self.transaction('boot', self.installed(data, bank=bank), banks=banks)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(f'open@{bank}', events)
                self.assertEqual([e for e in events if e.startswith('compare') and '@' in e],
                                 [f'compare-kernel@{bank}', f'compare-dtb@{bank}'])

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

    def test_faults_after_the_checks_never_select_the_target(self):
        for fault in ('verify', 'select-stock', 'kernel', 'dtb', 'write', 'readback', 'corrupt'):
            for banks in ('r1sf', 's0ss'):
                target = self.TARGETS[banks]
                with self.subTest(fault=fault, banks=banks):
                    d, r, events = self.transaction(fault, banks=banks)
                    self.assertNotEqual(r.returncode, 0)
                    self.assertNotIn('activate', events)
                    self.assertEqual((d / f'volume{1 - target}').read_bytes(), b'previous volume %d' % (1 - target))
                    if fault in ('verify', 'select-stock', 'kernel', 'dtb'):
                        self.assertNotIn('write', events)
                        self.assertEqual((d / f'volume{target}').read_bytes(), b'previous volume %d' % target)


if __name__ == '__main__':
    unittest.main()
