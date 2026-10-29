# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise receiver framing/state with a PTY, including corrupt/interrupted uploads."""
import hashlib
import importlib.util
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import tempfile
import time
import tty
import unittest
import sys
import zlib

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / 'br-external/package/fpvos-update'
SRC = PKG / 'src'
BACKEND = PKG / 'backends/ar9311'
sys.path.insert(0, str(ROOT / 'tools/fpvos-update'))
from boards import get_profile
BOARD = get_profile('ar9311')

def compile_framework(destination):
    profile = destination / 'profile.c'
    subprocess.run([sys.executable, str(PKG / 'generate-profile.py'), str(BACKEND / 'profile.json'), str(profile)], check=True)
    for name in ('receiver', 'verify'):
        files = [str(SRC / f'{name}.c'), str(profile)]
        if name == 'verify':
            files.append(str(BACKEND / 'images.c'))
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', f'-DCLEAN_BOOT_MARKER="{destination / "clean-boot"}"', '-I'+str(SRC), *files, '-o', str(destination/name)], check=True)


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'tools/fpvos-update/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLIENT, PACKAGE = load('client'), load('package')


def uimage(data, kind, comp, address):
    h = bytearray(64)
    struct.pack_into('>7I4B', h, 0, 0x27051956, 0, 0, len(data), address, address,
                     zlib.crc32(data), 5, 22, kind, comp)
    struct.pack_into('>I', h, 4, zlib.crc32(h))
    return bytes(h) + data


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.bin = Path(cls.build.name)
        compile_framework(cls.bin)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.master, slave = pty.openpty()
        tty.setraw(self.master)
        tty.setraw(slave)
        helper = self.dir / 'helper'
        helper.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "' + str(self.dir / 'calls') + '"\n')
        helper.chmod(0o700)
        stage = self.dir / 'stage'
        stage.mkdir(mode=0o700)
        self.process = subprocess.Popen([str(self.bin / 'receiver'), os.ttyname(slave), str(stage), str(helper)])
        self.slave = slave
        self.client = CLIENT.Client(self.master, BOARD, timeout=2)
        self.client.info()

    def tearDown(self):
        self.process.terminate()
        self.process.wait(timeout=3)
        os.close(self.master)
        os.close(self.slave)
        (self.bin / "clean-boot").unlink(missing_ok=True)
        self.temp.cleanup()

    def start(self, data, destination=CLIENT.VERIFY_DESTINATION, md5=None):
        self.client.clean()
        self.client.ack(0x72)
        self.client.ack(0x73, struct.pack('<64sii128s128s',
                        (md5 or hashlib.md5(data).hexdigest()).encode(), len(data), 1,
                        destination.encode(), b'host'))

    def test_full_transfer_reports_verified_not_installed(self):
        data = os.urandom(2 * 1024 * 1024 + 123)
        path = self.dir / 'test.fwu'
        path.write_bytes(data)
        result = self.client.verify(path)
        self.assertFalse(result['installed'])
        self.assertEqual(result['state'], 2)
        self.assertEqual((self.dir / 'stage/package.fwu').read_bytes(), data)
        self.assertEqual((self.dir / 'calls').read_text(), 'clean\nverify\n')

    def test_missing_md5_helper_is_not_reported_as_data_corruption(self):
        arguments = self.process.args
        self.process.terminate(); self.process.wait(timeout=3)
        self.process = subprocess.Popen(arguments, env={**os.environ, 'PATH':'/no-host-path-inside-chroot'})
        self.client.info()
        self.start(b'valid transfer', destination=CLIENT.DESTINATION)
        self.client.ack(0x74, b'valid transfer')
        with self.assertRaisesRegex(ValueError, 'MD5 helper failed'):
            self.client.ack(0x75)
        self.assertEqual((self.dir/'calls').read_text(), 'clean\n')
        self.assertFalse((self.dir/'stage/package.fwu').exists())

    def test_install_worker_and_failure(self):
        helper = self.dir / 'helper'
        status = self.dir / 'stage/status'
        data = self.dir / 'test.fwu'
        data.write_bytes(b'test worker')
        helper.write_text(f'#!/bin/sh\nif [ "$1" = install ]; then\nsleep .1\necho "100 4 installed" > "{status}"\nfi\n')
        result = self.client.verify(data, install=True)
        self.assertTrue(result['installed'])
        self.assertEqual(result['state'], 4)
        helper.write_text(f'#!/bin/sh\nif [ "$1" = install ]; then\necho "0 -2 restoration failed" > "{status}"\nexit 1\nfi\n')
        with self.assertRaisesRegex(RuntimeError, 'restoration failed'):
            self.client.verify(data, install=True)
        with self.assertRaisesRegex(ValueError, 'blocked'):
            self.client.ack(3, b'reboot' + bytes(26))
        with self.assertRaisesRegex(ValueError, 'restoration failed'):
            self.client.clean()
        self.assertTrue((self.dir / 'stage/package.fwu').exists())
        arguments = self.process.args
        self.process.terminate()
        self.process.wait(timeout=3)
        self.process = subprocess.Popen(arguments)
        with self.assertRaisesRegex(ValueError, 'blocked'):
            self.client.ack(3, b'reboot' + bytes(26))
        self.assertTrue((self.dir / 'stage/package.fwu').exists())

    def test_worker_completes_after_receiver_termination(self):
        helper = self.dir / 'helper'
        status = self.dir / 'stage/status'
        helper.write_text(f'#!/bin/sh\nif [ "$1" = install ]; then\nsleep .3\necho "100 4 installed" > "{status}"\nfi\n')
        self.start(b'payload', destination=CLIENT.DESTINATION)
        self.client.ack(0x74, b'payload')
        self.client.ack(0x75)
        self.process.terminate()
        self.process.wait(timeout=3)
        self.assertEqual(status.read_text().strip(), '100 4 installed')

    def test_receiver_accepts_legacy_transfer_destination(self):
        self.start(b'abcd', destination=BOARD['legacy_destination'] + '.verify')
        self.client.ack(0x74, b'abcd')
        self.client.ack(0x75)
        self.assertEqual((self.dir / 'stage/package.fwu').read_bytes(), b'abcd')

    def test_board_bundle_limit_is_checked_before_staging(self):
        self.client.clean()
        limit = max(BOARD['bundle_limits'])
        for size in (limit+1, 60*1024*1024):
            self.client.ack(0x72)
            with self.assertRaisesRegex(ValueError, 'invalid size'):
                self.client.ack(0x73, struct.pack('<64sii128s128s', b'0'*32,
                                size, 1, CLIENT.DESTINATION.encode(), b'host'))
            self.assertFalse((self.dir / 'stage/package.fwu').exists())
        # Exactly at the limit is accepted without sending/allocating the payload.
        self.client.ack(0x73, struct.pack('<64sii128s128s', b'0'*32,
                        limit, 1, CLIENT.DESTINATION.encode(), b'host'))
        self.assertEqual((self.dir / 'stage/package.fwu').stat().st_size, 0)

    def test_install_delegates_validation_to_transaction_once(self):
        helper = self.dir / 'helper'
        helper.write_text(f'''#!/bin/sh
printf "%s\\n" "$1" >> "{self.dir / 'calls'}"
[ "$1" != verify ] || exit 99
if [ "$1" = install ]; then echo '100 4 installed' > "{self.dir / 'stage/status'}"; fi
''')
        path = self.dir / 'test.fwu'; path.write_bytes(b'worker verification fixture')
        self.assertTrue(self.client.verify(path, install=True)['installed'])
        self.assertEqual((self.dir / 'calls').read_text(), 'clean\ninstall\n')

    def test_clean_boot_runs_readiness_once_and_fails_closed(self):
        args = self.process.args
        self.process.terminate(); self.process.wait(timeout=3)
        (self.bin / 'clean-boot').touch()
        self.process = subprocess.Popen(args)
        self.client.info()
        self.client.ack(0x72)  # Ready without another explicit clean request.
        self.assertEqual((self.dir / 'calls').read_text(), 'clean\n')
        self.process.terminate(); self.process.wait(timeout=3)
        (self.dir / 'helper').write_text('#!/bin/sh\nexit 1\n')
        self.process = subprocess.Popen(args, stderr=subprocess.PIPE)
        self.assertNotEqual(self.process.wait(timeout=3), 0)
        self.assertIn(b'clean-mode startup failed', self.process.stderr.read())
        self.process.stderr.close()

    def test_failed_restore_status_is_not_overridden_by_clean_boot(self):
        args = self.process.args
        self.process.terminate(); self.process.wait(timeout=3)
        (self.bin / 'clean-boot').touch()
        (self.dir / 'stage/status').write_text('0 -2 restoration failed\n')
        (self.dir / 'stage/package.fwu').write_bytes(b'evidence')
        self.process = subprocess.Popen(args)
        self.client.info()
        with self.assertRaisesRegex(ValueError, 'restoration failed'):
            self.client.clean()
        self.assertFalse((self.dir / 'calls').exists())
        self.assertEqual((self.dir / 'stage/package.fwu').read_bytes(), b'evidence')

    def test_atomic_package_replace_respects_umask(self):
        self.fixture()
        for mask, expected in ((0o022, 0o644), (0o077, 0o600)):
            path = self.dir / 'output.fwu'
            subprocess.run([sys.executable, str(ROOT / 'tools/fpvos-update/package.py'),
                            '--board', 'ar9311', '--replace', str(self.dir/'images'), str(path)],
                           umask=mask, check=True, capture_output=True)
            self.assertEqual(path.stat().st_mode & 0o777, expected)

    def test_requires_clean_mode(self):
        with self.assertRaisesRegex(ValueError, 'clean mode'):
            self.client.ack(0x72)

    def test_destination_cannot_escape(self):
        for destination in ('/etc/passwd', '/tmp/pc/../passwd', '/tmp/pc/fpvos-ar9311.fwu.extra'):
            with self.assertRaisesRegex(ValueError, 'destination'):
                self.start(b'abc', destination)
        self.assertFalse((self.dir / 'stage/package.fwu').exists())

    def test_incomplete_and_overrun(self):
        self.start(b'abcd')
        self.client.ack(0x74, b'ab')
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.client.ack(0x75)
        with self.assertRaisesRegex(ValueError, 'overrun'):
            self.client.ack(0x74, b'cde')
        self.client.ack(0x74, b'cd')
        self.client.ack(0x75)

    def test_duplicate_is_not_appended_and_changed_retry_rejected(self):
        self.start(b'abcd')
        seq = self.client.sequence
        self.client.ack(0x74, b'ab')
        self.client.sequence = seq
        self.client.ack(0x74, b'ab')
        self.client.sequence = seq
        with self.assertRaisesRegex(ValueError, 'changed retransmission'):
            self.client.ack(0x74, b'zz')
        self.client.ack(0x74, b'cd')
        self.client.ack(0x75)
        self.assertEqual((self.dir / 'stage/package.fwu').read_bytes(), b'abcd')

    def test_md5_failure_deletes_staging(self):
        self.start(b'abcd', md5='0' * 32)
        self.client.ack(0x74, b'abcd')
        with self.assertRaisesRegex(ValueError, 'MD5'):
            self.client.ack(0x75)
        self.assertFalse((self.dir / 'stage/package.fwu').exists())
        self.assertEqual((self.dir / 'calls').read_text(), 'clean\n')

    def test_bad_crc_does_not_write(self):
        self.start(b'abcd')
        packet = CLIENT.packet(0x74, b'abcd', self.client.sequence)
        packet[-1] ^= 1
        os.write(self.master, packet)
        h = self.client.exact(36, time.monotonic() + 2)
        b = self.client.exact(CLIENT.HEADER.unpack(h)[8], time.monotonic() + 2)
        self.assertEqual(struct.unpack_from('<i', b, 12)[0], -1)
        self.assertEqual((self.dir / 'stage/package.fwu').stat().st_size, 0)
        self.client.ack(0x74, b'abcd')
        self.client.ack(0x75)

    def test_fragmented_header_and_data(self):
        packet = CLIENT.packet(0x3c, sequence=34)
        for byte in packet:
            os.write(self.master, bytes([byte]))
        h = self.client.exact(36, time.monotonic() + 2)
        self.assertEqual(CLIENT.HEADER.unpack(h)[9], 34)
        self.assertEqual(len(self.client.exact(300, time.monotonic() + 2)), 300)

    def test_oversized_frame_disconnects_without_allocation(self):
        h = bytearray(CLIENT.packet(0x74))
        struct.pack_into('<I', h, 20, 0x7fffffff)
        os.write(self.master, h)
        self.process.wait(timeout=2)
        self.assertFalse((self.dir / 'stage/package.fwu').exists())

    def fixture(self):
        images = self.dir / 'images'
        images.mkdir()
        kernel = uimage(b'fake LZ4 payload', 2, 5, 0x20200000)
        data = kernel + bytes(-(64 + len(kernel)) % 256)
        h = bytearray(64)
        h[:4] = b'OTRA'
        struct.pack_into('<II', h, 12, 0x20200000, len(data))
        struct.pack_into('<I', h, 32, sum(data))
        (images / BOARD['names'][0]).write_bytes(h + data)
        value = b'caddx,ascent-gnd485\0artosyn,proxima-9311\0'
        structure = struct.pack('>IIIII', 1, 0, 3, len(value), 0) + value
        structure += bytes(-len(structure) % 4) + struct.pack('>II', 2, 9)
        strings = b'compatible\0'
        dtb = struct.pack('>10I', 0xd00dfeed, 56 + len(structure) + len(strings),
                          56, 56 + len(structure), 40, 17, 16, 0, len(strings), len(structure))
        (images / BOARD['names'][1]).write_bytes(dtb + bytes(16) + structure + strings)
        (images / BOARD['names'][2]).write_bytes(uimage(b'\x1f\x8bfake gzip', 3, 0, 0))
        return bytearray(PACKAGE.build(images, BOARD))

    def verify_package(self, data):
        source = self.dir / 'bundle'
        source.write_bytes(data)
        with tempfile.TemporaryDirectory(dir=self.dir) as output:
            return subprocess.run([str(self.bin / 'verify'), str(source), output], capture_output=True).returncode

    def test_full_vendor_restore_and_trailing_integrity(self):
        self.fixture()
        kernel = bytearray((self.dir / 'images/kernel.img').read_bytes())
        struct.pack_into('<I', kernel, 12, 0x200a0000)
        struct.pack_into('>II', kernel, 64+16, 0x200a0000, 0x200a0000)
        struct.pack_into('>I', kernel, 64+4, 0)
        struct.pack_into('>I', kernel, 64+4, zlib.crc32(kernel[64:128]))
        struct.pack_into('<I', kernel, 32, sum(kernel[64:]))
        kernel += b'Z' * (0x600000-len(kernel))
        dtb = (self.dir / 'images/ascent-gnd485.dtb').read_bytes()
        dtb += b'Y' * (0x60000-len(dtb))
        (self.dir / 'kernel.before.bin').write_bytes(kernel)
        (self.dir / 'dtb.before.bin').write_bytes(dtb)
        data = bytearray(PACKAGE.build(self.dir, BOARD, vendor_restore=True))
        self.assertEqual(self.verify_package(data), 0)
        data[-1] ^= 1
        self.assertNotEqual(self.verify_package(data), 0)
        (self.dir / 'dtb.before.bin').write_bytes(dtb[:-1])
        with self.assertRaisesRegex(ValueError, 'full-partition'):
            PACKAGE.build(self.dir, BOARD, vendor_restore=True)

    def test_package_integrity_board_and_size(self):
        data = self.fixture()
        self.assertEqual(self.verify_package(data), 0)
        for offset in (0, 12, 16, 96, 132, 508, 600, len(data)-1):
            changed = bytearray(data)
            changed[offset] ^= 1
            self.assertNotEqual(self.verify_package(changed), 0, offset)
        self.assertNotEqual(self.verify_package(data[:-1]), 0)
        self.assertNotEqual(self.verify_package(data + b'extra'), 0)
        changed = bytearray(data)
        struct.pack_into('<I', changed, 12, 486)
        struct.pack_into('<I', changed, 508, 0)
        struct.pack_into('<I', changed, 508, zlib.crc32(changed[:512]))
        self.assertNotEqual(self.verify_package(changed), 0)


if __name__ == '__main__':
    unittest.main()
