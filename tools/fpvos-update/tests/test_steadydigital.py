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
         'limits': [6291456, 61440, 25165824], 'counts': [3, 0], 'bundle_limits': [33554432, 512]}


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


# The stock table (layout.h): the pairs env..userapp at entries 2..11, bank A
# (suffix 0) even.
SD_PARTS = [('vendor', 0x180000, 0x80000), ('factory', 0x200000, 0x600000),
            ('env0', 0x800000, 0x60000), ('env1', 0x860000, 0x60000),
            ('uboot0', 0x8c0000, 0xc0000), ('uboot1', 0x980000, 0xc0000),
            ('kernel0', 0xa40000, 0x600000), ('kernel1', 0x1040000, 0x600000),
            ('dtb0', 0x1640000, 0x60000), ('dtb1', 0x16a0000, 0x60000),
            ('userapp0', 0x1700000, 0x2d00000), ('userapp1', 0x4400000, 0x2d00000),
            ('usr_data', 0x7100000, 0x600000), ('usr_log', 0x7700000, 0x600000)]
SD_GPT_BYTES = 0x4800
ATTRIBUTE = lambda i: 1024 + 128 * i + 48


def sd_record(bank=0):
    """One stock record as a unit ships: MBR, header, 128 entries, then the
    vendor table up to SD_GPT_BYTES."""
    g = bytearray(SD_GPT_BYTES)
    g[446:462] = bytes([0, 0, 2, 0, 0xee, 0xff, 0xff, 0xff, 1, 0, 0, 0, 0xff, 0xff, 3, 0]); g[510:512] = b'\x55\xaa'
    entries = bytearray(16384)
    for i, (name, start, size) in enumerate(SD_PARTS):
        e = 128 * i
        active = not 2 <= i <= 11 or (i - 2) % 2 == bank
        entries[e:e+32] = bytes([0xa0 + i]) * 16 + bytes([0x10 + i]) * 16
        struct.pack_into('<QQQ', entries, e + 32, start // 512, (start + size) // 512 - 1, int(active) << 47)
        entries[e+56:e+56+2*len(name)] = name.encode('utf-16le')
    # Stock leaves bytes after a name's NUL; a rewrite keeps them.
    entries[2*128 + 56 + 2*len('env0') + 2] = 0x41
    h = bytearray(92)
    h[:8] = b'EFI PART'
    struct.pack_into('<II', h, 8, 0x10000, 92)
    struct.pack_into('<QQQQ', h, 24, 1, 0x3ffff, 0xc00, 0x3ffde)
    h[56:72] = bytes(range(16))
    struct.pack_into('<QIII', h, 72, 2, 128, 128, zlib.crc32(entries))
    struct.pack_into('<I', h, 16, zlib.crc32(h))
    g[512:604] = h
    g[1024:1024+16384] = entries
    g[0x4400:] = (b'vendor table ' * 100)[:0x400]
    return bytes(g)


class SteadyDigitalFlashTests(unittest.TestCase):
    """flash.c on file-backed MTD (sd_flash_sim.c): the vendor's slot flip, the
    one GPT record rewritten in place, and what a failed rewrite leaves."""
    KERNEL_NAME = b'fpvOS SteadyDigital recovery'

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.build = Path(cls.temp.name)
        common = ['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-ffunction-sections', '-fdata-sections',
                  '-I' + str(SRC), '-I' + str(BACKEND), '-DP1_WORK="work"', '-DP1_ROOT="work/root"']
        renames = ['p1_stock', 'p1_mtd', 'p1_gpt_read']
        subprocess.run(common + ['-D' + s + '=unused_' + s for s in renames] +
                       ['-c', str(BACKEND / 'storage.c'), '-o', str(cls.build / 'storage.o')], check=True)
        subprocess.run(common + [str(Path(__file__).with_name('sd_flash_sim.c')), str(cls.build / 'storage.o'),
                                 '-Wl,--gc-sections'] +
                       ['-Wl,--wrap=' + s for s in ('open', 'ioctl', 'pwrite', 'pread', 'fsync')] +
                       ['-o', str(cls.build / 'flash')], check=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def directory(self, record=None):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); d = Path(temp.name)
        state = bytearray(b'\xff' * 0x80000)
        state[:SD_GPT_BYTES] = record or sd_record()
        (d / 'boot-state').write_bytes(state)
        for bank in (0, 1):
            (d / f'kernel{bank}').write_bytes(b'\x55' * 0x600000)
            (d / f'dtb{bank}').write_bytes(b'\x55' * 0x60000)
        return d

    def run_flash(self, d, *args, stock=False):
        env = {**os.environ, 'SD_STOCK': '1' if stock else '0'}
        return subprocess.run([str(self.build / 'flash'), *map(str, args)], cwd=d, capture_output=True, text=True, env=env)

    def select(self, d, bank, fault=0, stock=False):
        r = self.run_flash(d, 'select', bank, fault, stock=stock)
        return r.returncode, int(r.stdout), r.stderr

    def check_record(self, g, bank):
        """Both CRCs right and every pair's active member in BANK."""
        self.assertEqual(struct.unpack_from('<I', g, 512 + 88)[0], zlib.crc32(g[1024:1024+16384]))
        h = bytearray(g[512:604]); struct.pack_into('<I', h, 16, 0)
        self.assertEqual(struct.unpack_from('<I', g, 512 + 16)[0], zlib.crc32(h))
        for i in range(14):
            active = not 2 <= i <= 11 or (i - 2) % 2 == bank
            self.assertEqual(struct.unpack_from('<Q', g, ATTRIBUTE(i))[0], int(active) << 47, SD_PARTS[i][0])

    def test_bank_flip_and_back_changes_only_the_attributes_and_crcs(self):
        for stock in (False, True):
            with self.subTest(stock=stock):
                d = self.directory(); before = (d / 'boot-state').read_bytes()
                rc, writes, err = self.select(d, 1, stock=stock)
                self.assertEqual(rc, 0, err)
                self.assertEqual(writes, 1)
                after = (d / 'boot-state').read_bytes()
                self.assertEqual(after[SD_GPT_BYTES:], before[SD_GPT_BYTES:])
                allowed = {ATTRIBUTE(i) + 5 for i in range(2, 12)} | set(range(512 + 16, 512 + 20)) | set(range(512 + 88, 512 + 92))
                changed = {i for i in range(SD_GPT_BYTES) if after[i] != before[i]}
                self.assertLessEqual(changed, allowed)
                self.assertLessEqual({ATTRIBUTE(i) + 5 for i in range(2, 12)}, changed)
                self.check_record(after, 1)
                self.assertEqual(after[:SD_GPT_BYTES], sd_record(1))
                rc, writes, err = self.select(d, 0, stock=stock)
                self.assertEqual(rc, 0, err)
                self.assertEqual((d / 'boot-state').read_bytes(), before)
                # Already selected: nothing written.
                self.assertEqual(self.select(d, 0, stock=stock)[:2], (0, 0))
                self.assertEqual((d / 'boot-state').read_bytes(), before)

    def test_failed_rewrite_puts_the_previous_record_back(self):
        # 1: torn write, 3: a wrong byte read back, 5: the new record reads
        # back with an uncorrectable ECC error.
        for fault in (1, 3, 5):
            with self.subTest(fault=fault):
                d = self.directory(); before = (d / 'boot-state').read_bytes()
                rc, writes, err = self.select(d, 1, fault)
                self.assertNotEqual(rc, 0)
                self.assertEqual(writes, 2)
                self.assertNotIn('keep the unit powered', err)
                self.assertEqual((d / 'boot-state').read_bytes(), before)
                rc, _, err = self.select(d, 1)
                self.assertEqual(rc, 0, err)
                self.check_record((d / 'boot-state').read_bytes(), 1)

    def test_a_record_that_cannot_be_put_back_is_reported(self):
        # 4: no erase works (the table is as it was, but nothing could be
        # written); 6: every read of the record after a write fails ECC;
        # 8: torn, and the erase before the write-back fails.
        for fault in (4, 6, 8):
            with self.subTest(fault=fault):
                d = self.directory(); before = (d / 'boot-state').read_bytes()
                rc, writes, err = self.select(d, 1, fault)
                self.assertNotEqual(rc, 0)
                self.assertIn('keep the unit powered', err)
                after = (d / 'boot-state').read_bytes()
                self.assertEqual(after[SD_GPT_BYTES:], before[SD_GPT_BYTES:])
                if fault in (4, 6):
                    self.assertEqual(after, before)

    def test_nothing_is_written_unless_the_block_holds_only_the_record(self):
        d = self.directory()
        state = bytearray((d / 'boot-state').read_bytes()); state[0x10000] = 0
        (d / 'boot-state').write_bytes(state)
        self.assertEqual(self.select(d, 1)[:2], (1, 0))
        self.assertEqual((d / 'boot-state').read_bytes(), state)
        # A bad first block, or a table that is not the stock one: refused.
        d = self.directory(); before = (d / 'boot-state').read_bytes()
        self.assertEqual(self.select(d, 1, 2)[:2], (1, 0))
        bad = bytearray(sd_record()); bad[ATTRIBUTE(3) + 5] |= 0x80   # both env active
        d = self.directory(bytes(bad))
        self.assertEqual(self.select(d, 1)[:2], (1, 0))
        self.assertEqual((d / 'boot-state').read_bytes()[:SD_GPT_BYTES], bytes(bad))

    def kernel_kind(self, data, bank=0, fault=0, at=0):
        d = self.directory()
        if data is not None:
            image = bytearray(b'\xff' * 0x600000); image[at:at+len(data)] = data
            (d / f'kernel{bank}').write_bytes(bytes(image))
        else:
            (d / f'kernel{bank}').write_bytes(b'\xff' * 0x600000)
        r = self.run_flash(d, 'kind', bank, fault)
        self.assertEqual(r.returncode, 0, r.stderr)
        return int(r.stdout)

    def kernel_header(self, name):
        h = bytearray(128); h[:4] = b'OTRA'; struct.pack_into('>I', h, 64, 0x27051956)
        h[96:96+len(name)] = name; return bytes(h)

    def test_the_kernel_partition_says_whose_kernel_it_holds(self):
        ours = self.KERNEL_NAME
        self.assertEqual(self.kernel_kind(self.kernel_header(ours)), 1)
        self.assertEqual(self.kernel_kind(self.kernel_header(ours), bank=1), 1)
        # Another kernel - stock's, or the P1's - and one whose name only starts like ours.
        self.assertEqual(self.kernel_kind(self.kernel_header(b'Linux-4.9.38')), 0)
        self.assertEqual(self.kernel_kind(self.kernel_header(b'fpvOS P1 recovery')), 0)
        self.assertEqual(self.kernel_kind(self.kernel_header(ours + b' 2')), 0)
        # Erased, not an OTRA/uImage kernel, or unreadable: nobody's.
        self.assertEqual(self.kernel_kind(None, bank=1), -1)
        self.assertEqual(self.kernel_kind(b'OTRA' + bytes(124)), -1)
        self.assertEqual(self.kernel_kind(self.kernel_header(ours), fault=9), -1)
        # A bad first block is skipped, as SPL and the writer skip it.
        self.assertEqual(self.kernel_kind(self.kernel_header(ours), fault=2, at=0x20000), 1)

    def test_kernel_and_dtb_writes_go_to_the_bank_and_read_back(self):
        for bank in (0, 1):
            for index, size in ((0, 0x600000), (1, 0x60000)):
                with self.subTest(bank=bank, index=index):
                    d = self.directory(); image = bytes(range(256)) * 1200
                    (d / 'image').write_bytes(image)
                    part = ('kernel', 'dtb')[index]
                    self.assertEqual(self.run_flash(d, 'write', 'image', 0, bank, index).returncode, 0)
                    data = (d / f'{part}{bank}').read_bytes()
                    self.assertEqual(data[:len(image)], image)
                    self.assertEqual(data[len(image):0x60000], b'\xff' * (0x60000 - len(image)))
                    self.assertEqual((d / f'{part}{1 - bank}').read_bytes(), b'\x55' * size)
                    self.assertEqual(self.run_flash(d, 'compare', 'image', 0, bank, index).returncode, 0)
                    for fault in (1, 3, 4):
                        self.assertNotEqual(self.run_flash(d, 'write', 'image', fault, bank, index).returncode, 0)


class SignalTests(unittest.TestCase):
    def test_writes_ignore_the_signals_a_reboot_sends(self):
        """A reboot from SSH (SIGTERM to all) must not stop an install or the
        stock selection between an erase and its write: install and stock
        ignore SIGHUP, SIGINT and SIGTERM first, as the Ascent VRX's does."""
        for backend in ('p1-air', 'skyzone-' + 'steadydigital'):
            with self.subTest(backend):
                source = (BACKEND.parent / backend / 'nand.c').read_text()
                hold = source[source.index('static void hold_signals(void)'):]
                hold = hold[:hold.index('}')]
                for signal in ('SIGHUP', 'SIGINT', 'SIGTERM'):
                    self.assertIn(f'signal({signal},SIG_IGN)', hold)
                main = source[source.index('int main('):]
                install = main[main.index('"install"'):]
                self.assertLess(install.index('hold_signals();'), install.index('transaction('))
                stock = main[main.index('"stock"'):]
                self.assertLess(stock.index('hold_signals();'), stock.index('p1_select_bank('))


if __name__ == '__main__':
    unittest.main()
