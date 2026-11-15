# SPDX-License-Identifier: GPL-2.0-or-later
"""The Ascent Lite backend against a simulated unit: the stock dialect the
vendor's PC tool and the fpvOS Flasher expect, and the flash itself on files
standing in for the MTD partitions (FPVOS_LITE_ROOT), power cuts included."""
import hashlib
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import time
import tty
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / 'br-external/package/fpvos-update'
SRC = PKG / 'src'
BACKEND = PKG / 'backends/ascent-lite'
KiB, MiB = 1024, 1024 * 1024
BLOCK = 128 * KiB

# The Lite+'s /proc/mtd: boot, env, sel, kernel0/1, factory, rootfs0/1, usrdata0/1.
SIZES = [512 * KiB, 512 * KiB, 1 * MiB, 4 * MiB, 4 * MiB, 6 * MiB, 16 * MiB, 16 * MiB, 32 * MiB, 32 * MiB]
BANK = {0: (3, 6, 8), 1: (4, 7, 9)}
APP_VERSION = 'APP_VERSION=18.21.10\nBOARD_TYPE=Sky482\nBUILD_TIME=202608141800\nROLLBACK_FLAG=1\n'


def bsel(bank):
    return b'BSEL' + bytes([bank, 0xff ^ bank]) + b'\xee\x98\x0c\x53'


def asw(sections, board=3, version=(18, 21, 10), upgrade=(1, 1, 1, 1, 1)):
    """An ASW container as boot/mkascentimg.py writes one."""
    h = bytearray(0x80)
    h[0:4] = b'ASW\0'
    h[4] = board
    struct.pack_into('<III', h, 8, *version)
    off = 0x80
    for i, data in enumerate(sections):
        struct.pack_into('<BBBBII', h, 0x14 + 12 * i, i, upgrade[i], 1, 0, 0x80000, off)
        off += len(data)
    payload = b''.join(sections)
    struct.pack_into('<II', h, 0x70, zlib.crc32(payload), 0x80 + len(payload))
    return bytes(h) + payload


def frame(cmd, payload=b'', seq=1, retry=0):
    h = bytearray(struct.pack('<4sHHHHIHHIII', b'OTRA', 3292, 1, 0, 0xabcd, cmd, 2, 0,
                              len(payload), seq, retry)) + b'\0\0\0\0'
    struct.pack_into('<I', h, 32, zlib.crc32(bytes(h) + payload))
    return bytes(h) + payload


def text(b):
    return b.split(b'\0', 1)[0].decode()


class Unit:
    """A simulated Lite+ booted from bank 1, with the build of this tree as its
    updater."""

    def __init__(self, bin_dir, boot=None, env=None):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for d in ('dev', 'run', 'etc', 'factory', 'tmp', 'usrdata/fpv/air', 'sys/class/ubi', 'proc'):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        self.boot = boot if boot is not None else os.urandom(270848)
        self.env = env if env is not None else os.urandom(256 * KiB)
        for n, size in enumerate(SIZES):
            fill = bytes([0x40 + n]) * size
            (self.root / f'dev/mtd{n}').write_bytes(fill)
        self.put(0, self.boot + bytes(-len(self.boot) % BLOCK))
        self.put(1, self.env)
        self.put(2, b''.join(bsel(1).ljust(2048, b'\xff').ljust(BLOCK, b'\xff') for _ in range(8)))
        (self.root / 'run/bootsel1').write_text('normal check\n')
        (self.root / 'etc/app.version').write_text(APP_VERSION)
        (self.root / 'factory/mp_cfg.json').write_text('{\n    "sn": "0205",\n    "bb_power_offset": [0, 0]\n}\n')
        (self.root / 'chip_id').write_text('0x3516c613\n')
        (self.root / 'proc/mounts').write_text('')
        self.exe = Path(bin_dir) / 'ar_fpvhs_upgrade'
        self.process = None

    def put(self, n, data, at=0):
        with open(self.root / f'dev/mtd{n}', 'r+b') as f:
            f.seek(at)
            f.write(data)

    def mtd(self, n):
        return (self.root / f'dev/mtd{n}').read_bytes()

    def environ(self, **extra):
        return dict(os.environ, FPVOS_LITE_ROOT=str(self.root), **extra)

    def start(self, clean, rf=16):
        self.master, slave = pty.openpty()
        tty.setraw(self.master)
        tty.setraw(slave)
        self.slave = slave
        # As stock's scripts start it: the board's options in the normal
        # system only.
        args = ['-c', '0', '-m', '1'] if clean else ['-c', '1', '-m', '1', '-b', '19', '-r', str(rf), '-t', '472', '-e', '16']
        self.process = subprocess.Popen(
            [str(self.exe), *args],
            env=self.environ(FPVOS_LITE_TTY=os.ttyname(slave)), start_new_session=True,
            stderr=subprocess.DEVNULL)
        self.seq = 0

    def stop(self):
        if self.process:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait()
            os.close(self.master)
            os.close(self.slave)
            self.process = None

    def close(self):
        self.stop()
        self.temp.cleanup()

    def read(self, n, deadline):
        out = b''
        while len(out) < n:
            left = deadline - time.time()
            if left <= 0:
                raise TimeoutError(f'{len(out)} of {n} bytes')
            r, _, _ = select.select([self.master], [], [], left)
            if r:
                out += os.read(self.master, n - len(out))
        return out

    def send(self, cmd, payload=b'', retry=0, seq=None, timeout=10):
        """One request and its reply, as the PC tool sends it: seq from 0, one
        more each time, the same seq never sent twice."""
        if seq is None:
            seq, self.seq = self.seq, self.seq + 1
        os.write(self.master, frame(cmd, payload, seq, retry))
        deadline = time.time() + timeout
        h = self.read(36, deadline)
        n = struct.unpack_from('<I', h, 20)[0]
        b = self.read(n, deadline)
        assert h[:4] == b'OTRA' and h[6] == 2 and struct.unpack_from('<I', h, 12)[0] == cmd, h.hex()
        assert struct.unpack_from('<I', h, 24)[0] == seq
        crc = struct.unpack_from('<I', h, 32)[0]
        assert zlib.crc32(h[:32] + b'\0\0\0\0' + b) == crc
        return b

    def find(self):
        b = self.send(0x3c)
        assert len(b) == 300
        return {'chunk': struct.unpack_from('<I', b)[0], 'sdk': text(b[4:36]), 'name': text(b[36:100]),
                'firmware': text(b[104:168]), 'serial': text(b[168:200]),
                'hardware': text(b[200:232]), 'status': struct.unpack_from('<i', b, 232)[0],
                'detail': text(b[236:300])}

    def status(self):
        b = self.send(0x76)
        assert len(b) == 72
        return struct.unpack_from('<Ii', b) + (text(b[8:]),)

    def ack(self, b):
        assert len(b) in (68, 80), len(b)
        off = 12 if len(b) == 80 else 0
        return struct.unpack_from('<i', b, off)[0], text(b[off + 4:])

    def reboot(self, name):
        return self.ack(self.send(3, name.encode().ljust(32, b'\0')))

    def upload(self, image, destination='/tmp/pc/Ascent_H_Sky_18_21_10.img', resend=None):
        assert self.ack(self.send(0x72)) == (0, 'OK')
        info = (hashlib.md5(image).hexdigest().encode().ljust(64, b'\0') + struct.pack('<ii', len(image), 1) +
                destination.encode().ljust(128, b'\0') + b'C:\\fw\\image.img'.ljust(128, b'\0'))
        assert self.ack(self.send(0x73, info)) == (0, 'OK')
        for i, at in enumerate(range(0, len(image), MiB)):
            chunk = image[at:at + MiB]
            b = self.send(0x74, chunk)
            assert self.ack(b) == (0, 'OK')
            if resend == i:
                # The PC tool's resend of a chunk whose reply it missed.
                b = self.send(0x74, chunk, retry=1)
                assert self.ack(b) == (0, 'OK')
            assert struct.unpack_from('<I', b, 4)[0] == at + len(chunk), 'appended twice'
        return self.ack(self.send(0x75))

    def wait_installed(self, timeout=60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            percent, state, detail = self.status()
            assert state >= 0, detail
            assert not any(w in detail.lower() for w in ('fail', 'error', ' err')), detail
            if percent > 99:
                return state, detail
            time.sleep(0.2)
        raise TimeoutError('install did not finish')

    def rebooted(self, timeout=5):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if (self.root / 'rebooted').exists():
                return True
            time.sleep(0.05)
        return False


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        b = Path(cls.build.name)
        subprocess.run([sys.executable, str(PKG / 'generate-profile.py'), str(BACKEND / 'profile.json'), str(b / 'profile.c')], check=True)
        flags = ['-O2', '-Wall', '-Wextra', '-Werror', '-I' + str(SRC)]
        subprocess.run(['cc', *flags, '-Dmain=fpvos_receiver_main', '-c', str(SRC / 'receiver.c'), '-o', str(b / 'receiver.o')], check=True)
        subprocess.run(['cc', *flags, '-Dmain=fpvos_verify_main', '-c', str(SRC / 'verify.c'), '-o', str(b / 'verify.o')], check=True)
        subprocess.run(['cc', *flags, str(SRC / 'main.c'), str(b / 'receiver.o'), str(b / 'verify.o'), str(b / 'profile.c'),
                        str(BACKEND / 'lite.c'), '-o', str(b / 'ar_fpvhs_upgrade')], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def unit(self, **kw):
        u = Unit(self.build.name, **kw)
        self.addCleanup(u.close)
        return u

    def image_for(self, unit, boot=None, **kw):
        sections = [unit.boot if boot is None else boot, unit.env, os.urandom(3 * MiB + 1234),
                    os.urandom(5 * BLOCK), os.urandom(9 * BLOCK)]
        return sections, asw(sections, **kw)

    def assert_bank(self, unit, bank, sections, bad=()):
        """Each section where the bank's partition starts (bad blocks skipped),
        zeros to the end of its last block, every good block after it erased."""
        for i, n in zip((2, 3, 4), BANK[bank]):
            data = unit.mtd(n)
            blocks = [data[b * BLOCK:(b + 1) * BLOCK] for b in range(len(data) // BLOCK)]
            good = [blk for b, blk in enumerate(blocks) if (n, b) not in bad]
            written = b''.join(good)
            self.assertEqual(written[:len(sections[i])], sections[i], f'mtd{n}')
            pad = -len(sections[i]) % BLOCK
            self.assertEqual(written[len(sections[i]):len(sections[i]) + pad], bytes(pad))
            self.assertEqual(written[len(sections[i]) + pad:].strip(b'\xff'), b'', f'mtd{n} tail')

    def assert_selected(self, unit, bank):
        sel = unit.mtd(2)
        for b in range(len(sel) // BLOCK):
            self.assertEqual(sel[b * BLOCK:b * BLOCK + 10], bsel(bank))

    def test_identity_as_stock(self):
        """FIND_DEVICE as the stock updater answered on a Lite+ (472, -b 19
        -e 16, sn 0205): the vendor's PC tool and the Flasher key on it."""
        u = self.unit()
        u.start(clean=False)
        info = u.find()
        self.assertEqual(info, {'chunk': MiB, 'sdk': '', 'name': 'Ascent_lite_plus', 'firmware': 'Ascent_H_Sky_18_21_10',
                                'serial': '1_0205', 'hardware': 'FPV-Ascent-Sky-472-V1.3-1.0', 'status': 0,
                                'detail': 'normal mode'})
        self.assertEqual(u.status(), (0, 0, 'normal mode'))
        self.assertEqual(u.reboot('clean'), (0, 'rebooting into clean mode'))
        self.assertTrue(u.rebooted())
        self.assertEqual((u.root / 'factory/sirius-clean-system-flag').read_text(), 'usb\n')
        # The clean system: the same identity, from what the normal one kept.
        u.stop()
        u.start(clean=True)
        self.assertEqual(u.find(), dict(info, detail='clean RAM mode'))
        # Without it (the first clean boot after a stock updater), the board
        # type from the stock fpv_board_type file.
        u.stop()
        (u.root / 'usrdata/fpv/air/updater.board').unlink()
        (u.root / 'usrdata/fpv/fpv_board_type').write_text('472\n')
        u.start(clean=True)
        self.assertEqual(u.find()['name'], 'Ascent_lite_plus')

    def test_pc_tool_flash(self):
        """The PC tool's flash in the clean system: no FIND_DEVICE first, 1 MiB
        chunks, one resent under a new seq, FILE_END resent; the unit reboots by
        itself after 100 %. Bank 0 is written and selected, bank 1 untouched,
        U-Boot and its environment (the image's) not rewritten."""
        u = self.unit()
        sections, image = self.image_for(u)
        before = {n: u.mtd(n) for n in range(10)}
        u.start(clean=True)
        self.assertEqual(u.upload(image, resend=1), (0, 'OK'))
        self.assertEqual(u.ack(u.send(0x75, retry=1)), (0, 'OK'))
        self.assertEqual(u.find()['detail'][:0], '')
        state, detail = u.wait_installed()
        self.assertEqual((state, detail), (4, 'installed in bank 0'))
        self.assertTrue(u.rebooted())
        self.assert_bank(u, 0, sections)
        self.assert_selected(u, 0)
        for n in (0, 1, 4, 5, 7, 9):
            self.assertEqual(u.mtd(n), before[n], f'mtd{n} changed')

    def test_hardware_ends_in_the_rf_board(self):
        """As stock answers: a Lite+ with -r 17 (-e 16) is ...-1.1, in the
        normal and the clean system; a board file from an updater without -r
        (three numbers) gives -e's ...-1.0."""
        u = self.unit()
        u.start(clean=False, rf=17)
        self.assertEqual(u.find()['hardware'], 'FPV-Ascent-Sky-472-V1.3-1.1')
        u.stop()
        u.start(clean=True)
        self.assertEqual(u.find()['hardware'], 'FPV-Ascent-Sky-472-V1.3-1.1')
        u.stop()
        (u.root / 'usrdata/fpv/air/updater.board').write_text('472 19 16\n')
        u.start(clean=True)
        self.assertEqual(u.find()['hardware'], 'FPV-Ascent-Sky-472-V1.3-1.0')
        u.stop()

    def test_version_in_the_sdk_field(self):
        """The firmware field stays stock's (the PC tool's); fpvOS's own version
        from air/VERSION goes in the SDK field, without its newline."""
        u = self.unit()
        (u.root / 'usrdata/fpv/air/VERSION').write_text('2026.10.beta4-42-g3a8bff1\n')
        u.start(clean=False)
        info = u.find()
        self.assertEqual((info['sdk'], info['firmware']), ('2026.10.beta4-42-g3a8bff1', 'Ascent_H_Sky_18_21_10'))
        u.stop()

    def test_frequency_page_points_to_the_goggle(self):
        """The PC tool's radio frequency page (119-122) is answered with where
        fpvOS keeps those settings, in both systems."""
        u = self.unit()
        for clean in (False, True):
            u.start(clean=clean)
            for cmd in (0x77, 0x78, 0x79, 0x7a):
                self.assertEqual(u.ack(u.send(cmd)), (-1, 'frequency settings: use the goggle menu on fpvOS'))
            u.stop()

    def test_clean_in_clean_mode_reboots(self):
        """'clean' in the clean system takes the port down again (the Flasher
        waits for that)."""
        u = self.unit()
        u.start(clean=True)
        self.assertEqual(u.find()['detail'], 'clean RAM mode')
        self.assertEqual(u.reboot('clean'), (0, 'rebooting into clean mode'))
        self.assertTrue(u.rebooted())

    def test_fpvos_tool_waits_for_reboot(self):
        """fpvOS's tools (fpvos.fwu) send REBOOT themselves."""
        u = self.unit()
        sections, image = self.image_for(u)
        u.start(clean=True)
        self.assertEqual(u.upload(image, destination='/tmp/pc/fpvos.fwu'), (0, 'OK'))
        self.assertEqual(u.wait_installed()[0], 4)
        time.sleep(1.5)
        self.assertFalse((u.root / 'rebooted').exists())
        self.assertEqual(u.reboot('reboot'), (0, 'rebooting'))
        self.assertTrue(u.rebooted())

    def test_verify_only_writes_nothing(self):
        u = self.unit()
        _, image = self.image_for(u)
        before = {n: u.mtd(n) for n in range(10)}
        u.start(clean=True)
        self.assertEqual(u.upload(image, destination='/tmp/pc/fpvos.verify'), (0, 'OK'))
        self.assertEqual(u.status()[1], 2)
        self.assertEqual({n: u.mtd(n) for n in range(10)}, before)

    def test_new_uboot_written_last(self):
        """An image whose U-Boot differs (an older stock image): written, read
        back, then the bank switch."""
        u = self.unit()
        boot = os.urandom(236544)
        sections, image = self.image_for(u, boot=boot)
        u.start(clean=True)
        self.assertEqual(u.upload(image), (0, 'OK'))
        self.assertEqual(u.wait_installed()[0], 4)
        flash = u.mtd(0)
        self.assertEqual(flash[:len(boot)], boot)
        self.assertEqual(flash[len(boot):-len(boot) % BLOCK + len(boot)], bytes(-len(boot) % BLOCK))
        self.assert_selected(u, 0)

    def test_bad_blocks_skipped(self):
        u = self.unit()
        bad = {(6, 1), (8, 0), (8, 5), (3, 2)}
        for n, b in bad:
            with open(u.root / f'dev/mtd{n}.bad', 'a') as f:
                f.write(f'{b}\n')
            u.put(n, b'\xaa' * BLOCK, b * BLOCK)
        sections, image = self.image_for(u)
        u.start(clean=True)
        self.assertEqual(u.upload(image), (0, 'OK'))
        self.assertEqual(u.wait_installed()[0], 4)
        self.assert_bank(u, 0, sections, bad=bad)
        for n, b in bad:
            self.assertEqual(u.mtd(n)[b * BLOCK:(b + 1) * BLOCK], b'\xaa' * BLOCK, 'a bad block was written')

    def test_refused_images_write_nothing(self):
        u = self.unit()
        sections, good = self.image_for(u)
        corrupt = bytearray(good)
        corrupt[-5] ^= 1
        _, other_board = self.image_for(u, board=4)
        _, no_kernel = self.image_for(u, upgrade=(1, 1, 0, 1, 1))
        before = {n: u.mtd(n) for n in range(10)}
        u.start(clean=True)
        for image, why in ((bytes(corrupt), 'CRC'), (other_board, 'board'), (no_kernel, 'kernel'),
                           (b'FPVOSUP1' + bytes(2 * MiB), 'ASW')):
            self.assertEqual(u.upload(image), (0, 'OK'))
            deadline = time.time() + 20
            while time.time() < deadline:
                percent, state, detail = u.status()
                if state < 0:
                    break
                time.sleep(0.1)
            self.assertLess(state, 0)
            self.assertIn(why, detail)
            self.assertEqual({n: u.mtd(n) for n in range(10)}, before)
            u.stop()
            (u.root / 'tmp/fpvos-update/status').unlink(missing_ok=True)
            u.start(clean=True)

    def test_partition_in_use_refused(self):
        u = self.unit()
        (u.root / 'sys/class/ubi/ubi3').mkdir()
        (u.root / 'sys/class/ubi/ubi3/mtd_num').write_text('8\n')
        _, image = self.image_for(u)
        before = {n: u.mtd(n) for n in range(10)}
        img = u.root / 'tmp/image'
        img.write_bytes(image)
        r = subprocess.run([str(u.exe), 'install', str(img)], env=u.environ(FPVOS_LITE_HELPER='1'),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('mtd8 is in use', (u.root / 'tmp/status').read_text())
        self.assertEqual({n: u.mtd(n) for n in range(10)}, before)

    def test_power_cut_anywhere_keeps_the_booted_bank(self):
        """A power cut after any number of block writes: the boot bank stays the
        booted one until the new bank and the boot record are all written."""
        u = self.unit()
        sections, image = self.image_for(u)
        img = u.root / 'tmp/image'
        img.write_bytes(image)
        state = {n: u.mtd(n) for n in range(10)}
        # Count the block writes of a whole install.
        r = subprocess.run([str(u.exe), 'install', str(img)], env=u.environ(FPVOS_LITE_HELPER='1', FPVOS_LITE_CUT_AFTER='100000'),
                           capture_output=True)
        self.assertEqual(r.returncode, 0)
        self.assert_selected(u, 0)
        writes = None
        for cut in range(0, 2000):
            for n, data in state.items():
                u.put(n, data)
            img.write_bytes(image)
            r = subprocess.run([str(u.exe), 'install', str(img)], env=u.environ(FPVOS_LITE_HELPER='1', FPVOS_LITE_CUT_AFTER=str(cut)),
                               capture_output=True)
            if r.returncode == 0:
                writes = cut
                break
            self.assertEqual(r.returncode, 99)
            sel = u.mtd(2)
            records = {sel[b * BLOCK:b * BLOCK + 10] for b in range(len(sel) // BLOCK)}
            # Every intact record still names bank 1; a block being rewritten is
            # erased (U-Boot reads the first intact one, as ar_bsel does).
            self.assertTrue(records <= {bsel(1), bsel(0), b'\xff' * 10}, records)
            if bsel(0) in records:
                # Only once every bank-0 block is written.
                self.assert_bank(u, 0, sections)
            for n in (0, 1, 4, 7, 9):
                self.assertEqual(u.mtd(n), state[n], f'cut {cut}: mtd{n}')
        self.assertIsNotNone(writes)
        self.assertGreater(writes, 100)
        print(f"power cut: {writes} cut points, every one kept bank 1", file=sys.stderr)


if __name__ == '__main__':
    unittest.main()
