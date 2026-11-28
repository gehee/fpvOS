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
BACKEND = PKG / 'backends/ascent-vrx'
sys.path.insert(0, str(ROOT / 'tools/fpvos-update'))
from boards import get_profile
BOARD = get_profile('ascent-vrx')

def compile_framework(destination):
    profile = destination / 'profile.c'
    subprocess.run([sys.executable, str(PKG / 'generate-profile.py'), str(BACKEND / 'profile.json'), str(profile)], check=True)
    for name in ('receiver', 'verify'):
        files = [str(SRC / f'{name}.c'), str(profile)]
        if name == 'verify':
            files.append(str(BACKEND / 'images.c'))
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', f'-DCLEAN_BOOT_MARKER="{destination / "clean-boot"}"',
                        f'-DUSB_MODE_FILE="{destination / "usb-mode"}"', f'-DLOCATION_FILE="{destination / "location"}"', f'-DCLOCK_FILE="{destination / "clock"}"', f'-DRTC_DEVICE="{destination / "rtc"}"', f'-DSTOCK_ROOT_FILE="{destination / "stock-root"}"', f'-DVERSION_FILE="{destination / "fpvos-version"}"', '-I'+str(SRC), *files, '-o', str(destination/name)], check=True)


def compile_receiver(destination, name, *flags, sources=()):
    """A receiver built as compile_framework's, with test-only FLAGS and SOURCES."""
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', f'-DCLEAN_BOOT_MARKER="{destination / "clean-boot"}"',
                    f'-DUSB_MODE_FILE="{destination / "usb-mode"}"', f'-DLOCATION_FILE="{destination / "location"}"', f'-DCLOCK_FILE="{destination / "clock"}"', f'-DRTC_DEVICE="{destination / "rtc"}"', f'-DSTOCK_ROOT_FILE="{destination / "stock-root"}"', f'-DVERSION_FILE="{destination / "fpvos-version"}"',
                    *flags, '-I'+str(SRC), str(SRC / 'receiver.c'), str(destination / 'profile.c'),
                    *map(str, sources), '-o', str(destination / name)], check=True)
    return destination / name


# A board's destination hook (the Lite's kind): a refusal leaves the flags as
# they were.
DESTINATION_HOOK = r'''
#include <string.h>
int fpvos_board_destination(const unsigned char path[128], int *install, int *self_reboot)
{
	if (!memcmp(path, "/tmp/pc/fpvos.fwu", 18)) { *install = 1; *self_reboot = 0; return 1; }
	if (!memcmp(path, "/tmp/pc/fpvos.verify", 21)) { *install = 0; *self_reboot = 0; return 1; }
	return 0;
}
'''


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

    VARIANTS = dict(idle=(['-DTRANSFER_IDLE_SECONDS=1'], False), gap=(['-DREFRESH_GAP_US=300000'], False),
                    hook=([], True))

    def variant(self, name):
        """A test build of the receiver (built once, beside the class's own)."""
        path = self.bin / f'receiver-{name}'
        if not path.exists():
            flags, hook = self.VARIANTS[name]
            sources = []
            if hook:
                sources.append(self.bin / 'hook.c')
                sources[0].write_text(DESTINATION_HOOK)
            compile_receiver(self.bin, path.name, *flags, sources=sources)
        return path

    def restart(self, variant=None):
        """The receiver again on the same port and staging (VARIANT: a test build)."""
        arguments = list(self.process.args)
        self.process.terminate()
        self.process.wait(timeout=3)
        if variant:
            arguments[0] = str(self.variant(variant))
        self.process = subprocess.Popen(arguments)
        self.client.info()

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
        (self.bin / "location").unlink(missing_ok=True)
        (self.bin / "fpvos-version").unlink(missing_ok=True)
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

    def test_stock_return_is_acknowledged_before_reboot(self):
        self.client.ack(3, b'stock'.ljust(32, b'\0'))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if (self.dir / 'calls').read_text() == 'stock\nreboot\n':
                break
            time.sleep(.02)
        self.assertEqual((self.dir / 'calls').read_text(), 'stock\nreboot\n')

    def test_stock_return_rejects_malformed_active_and_unsupported_requests(self):
        with self.assertRaises(ValueError):
            self.client.ack(3, b'stock\0' + b'x' * 26)
        self.assertFalse((self.dir / 'calls').exists())
        self.start(b'pending upload')
        with self.assertRaises(ValueError):
            self.client.ack(3, b'stock'.ljust(32, b'\0'))
        self.assertNotIn('stock', (self.dir / 'calls').read_text())

    def test_backend_refusing_stock_return_does_not_reboot(self):
        (self.dir / 'helper').write_text('#!/bin/sh\nexit 2\n')
        with self.assertRaises(ValueError):
            self.client.ack(3, b'stock'.ljust(32, b'\0'))
        self.assertNotEqual(self.client.info()['detail'], '')

    def mode(self, name):
        reply = self.client.ack(3, name.encode().ljust(32, b'\0'))
        return reply[4:].split(b'\0')[0].decode()

    def wait_calls(self, expected):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and (
                not (self.dir / 'calls').exists() or (self.dir / 'calls').read_text() != expected):
            time.sleep(.02)
        self.assertEqual((self.dir / 'calls').read_text(), expected)

    def test_bridge_mode_through_helper_and_reported(self):
        # fpvos-usb writes the mode file; here the helper plays it.
        (self.dir / 'helper').write_text(
            f'#!/bin/sh\nprintf "%s\\n" "$1" >> "{self.dir / "calls"}"\n'
            f'[ "$1" != bridge ] || echo bridge > "{self.bin / "usb-mode"}"\n')
        self.addCleanup((self.bin / 'usb-mode').unlink, missing_ok=True)
        self.assertEqual(self.mode('bridge'), 'OK')
        self.assertEqual((self.dir / 'calls').read_text(), 'bridge\n')
        self.assertEqual(self.client.info()['detail'], 'bridge mode')
        # Back to normal, live: the mode file says so, and so does the info.
        (self.bin / 'usb-mode').write_text('normal\n')
        self.assertEqual(self.client.info()['detail'], 'normal mode')

    def test_bridge_mode_failure_is_refused(self):
        (self.dir / 'helper').write_text('#!/bin/sh\nexit 2\n')
        with self.assertRaisesRegex(ValueError, 'bridge mode unsupported'):
            self.mode('bridge')
        self.assertEqual(self.client.info()['detail'], 'normal mode')

    def test_normal_from_bridge_reboots_after_reply(self):
        helper = self.dir / 'helper'
        helper.write_text(f'#!/bin/sh\necho "$1" >> "{self.dir / "calls"}"\n[ "$1" != normal ] || exit 10\n')
        self.assertEqual(self.mode('normal'), 'rebooting into normal mode')
        self.wait_calls('normal\nreboot\n')

    def test_location_kept_for_kestrel_gnd(self):
        """SET_LOCATION (200), the Flasher's after a goggle's flash, in normal
        mode: kept in the profile's file as a script reads it, rewritten only
        when it changes; a field with a character a shell would see, too long or
        not NUL-padded, or a country that is not two letters, is refused and
        keeps the file."""
        def location(tz, zone='', country=''):
            return tz.encode().ljust(64, b'\0') + zone.encode().ljust(64, b'\0') + country.encode().ljust(8, b'\0')
        kept = self.bin / 'location'
        self.client.ack(200, location('CET-1CEST,M3.5.0,M10.5.0/3', 'Europe/Paris', 'FR'))
        self.assertEqual(kept.read_text(), "TZ='CET-1CEST,M3.5.0,M10.5.0/3'\nZONE='Europe/Paris'\nCOUNTRY='FR'\n")
        mtime = kept.stat().st_mtime_ns
        time.sleep(0.02)
        self.client.ack(200, location('CET-1CEST,M3.5.0,M10.5.0/3', 'Europe/Paris', 'FR'))
        self.assertEqual(kept.stat().st_mtime_ns, mtime)
        for bad in (location("UTC0'; reboot; '"), location('UTC0', 'Europe/Paris', 'FRA'),
                    location('UTC0', 'Europe/$(x)'), location('UTC'), location('UTC0', country='fr'),
                    location('UTC0')[:-1], b'UTC0'.ljust(64, b'\0') + b'x' * 64 + bytes(8),
                    location('UTC0')[:60] + b'\0\0\0x' + location('UTC0')[64:]):
            with self.assertRaisesRegex(ValueError, 'invalid location'):
                self.client.ack(200, bad)
        self.assertIn("Europe/Paris", kept.read_text())
        out = subprocess.run(['sh', '-c', '. "$1"; echo "$ZONE $COUNTRY"', 'sh', str(kept)],
                             capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, 'Europe/Paris FR')

    def test_time_set_from_the_flasher(self):
        """SET_TIME (201): the computer's clock in milliseconds; a unit with no
        battery clock says the time holds until power-off; a time before 2024
        or from 2100, or a payload not 8 bytes, is refused and sets nothing."""
        ms = 1795000000123
        reply = self.client.ack(201, struct.pack('<Q', ms))
        self.assertEqual(bytes(reply[4:]).rstrip(b'\0').decode(), 'set until power-off: no battery clock')
        self.assertEqual((self.bin / 'clock').read_text(), '1795000000.123\n')
        (self.bin / 'clock').unlink()
        for bad in (struct.pack('<Q', 1700000000000), struct.pack('<Q', 4102444800000), struct.pack('<I', 1795000000), b''):
            with self.assertRaisesRegex(ValueError, 'invalid time'):
                self.client.ack(201, bad)
        self.assertFalse((self.bin / 'clock').exists())

    def test_stock_root_reports_the_helpers_fingerprint(self):
        """STOCK_ROOT (202): the helper's stock-root writes the stock system's
        SHA-256, sent whole (64 hex characters after the status); a helper
        without stock-root (exit 2) is 'not available'; its reason otherwise."""
        helper = self.dir / 'helper'
        kept = self.bin / 'stock-root'
        digest = 'ab' * 32
        helper.write_text(f'#!/bin/sh\n[ "$1" = stock-root ] || exit 0\nprintf "%s\\n" {digest} > "{kept}"\n')
        reply = self.client.ack(202, b'')
        self.assertEqual(bytes(reply[:4]), bytes(4))
        self.assertEqual(bytes(reply[4:68]).decode(), digest)
        helper.write_text('#!/bin/sh\nexit 2\n')
        with self.assertRaisesRegex(ValueError, 'not available on this unit'):
            self.client.ack(202, b'')
        helper.write_text('#!/bin/sh\necho "stock bank: not UBI" >&2\nexit 1\n')
        with self.assertRaisesRegex(ValueError, 'stock bank: not UBI'):
            self.client.ack(202, b'')

    def test_normal_in_normal_mode_is_ok(self):
        self.assertEqual(self.mode('normal'), 'OK')
        self.assertEqual((self.dir / 'calls').read_text(), 'normal\n')

    def test_update_is_clean_mode(self):
        self.assertEqual(self.mode('update'), 'OK')
        self.assertEqual((self.dir / 'calls').read_text(), 'clean\n')
        self.assertEqual(self.client.info()['detail'], 'clean RAM mode')
        with self.assertRaisesRegex(ValueError, 'not available in update mode'):
            self.mode('bridge')
        self.assertEqual(self.mode('normal'), 'rebooting into normal mode')
        self.wait_calls('clean\nreboot\n')

    def test_mode_names_must_be_exact(self):
        for bad in (b'bridge\0x', b'bridgex', b'normal\0\0y'):
            with self.assertRaises(ValueError):
                self.client.ack(3, bad.ljust(32, b'\0'))
        self.assertFalse((self.dir / 'calls').exists())

    def test_bridge_mode_survives_receiver_restart(self):
        (self.bin / 'usb-mode').write_text('bridge\n')
        try:
            self.tearDown()
            self.setUp()
            self.assertEqual(self.client.info()['detail'], 'bridge mode')
        finally:
            (self.bin / 'usb-mode').unlink()

    def test_clean_boot_runs_readiness_once(self):
        args = self.process.args
        self.process.terminate(); self.process.wait(timeout=3)
        (self.bin / 'clean-boot').touch()
        self.process = subprocess.Popen(args)
        self.client.info()
        self.client.ack(0x72)  # Ready without another explicit clean request.
        self.assertEqual((self.dir / 'calls').read_text(), 'clean\n')

    def test_clean_boot_failure_remains_queryable_and_retryable(self):
        args = self.process.args
        self.process.terminate(); self.process.wait(timeout=3)
        (self.bin / 'clean-boot').touch()
        helper = self.dir / 'helper'
        helper.write_text(f'#!/bin/sh\necho "$1" >> "{self.dir / "calls"}"\nexit 7\n')
        self.process = subprocess.Popen(args)
        for _ in range(2):
            self.assertIn('clean-mode startup failed', self.client.info()['detail'])
            status = self.client.exchange(0x76)
            self.assertEqual(struct.unpack_from('<Ii', status), (0, -1))
            self.assertIn(b'clean-mode startup failed', status[8:])
            self.assertIsNone(self.process.poll())
        self.assertEqual((self.dir / 'calls').read_text(), 'clean\n')
        for command, payload in ((0x72, b''), (0x73, bytes(328)),
                                 (0x74, b'payload'), (0x75, b'')):
            with self.assertRaisesRegex(ValueError, 'clean mode'):
                self.client.ack(command, payload)
        self.assertFalse((self.dir / 'stage/package.fwu').exists())
        with self.assertRaisesRegex(ValueError, 'clean-mode preparation failed'):
            self.client.clean()
        self.assertIn('clean-mode preparation failed', self.client.info()['detail'])
        self.assertEqual((self.dir / 'calls').read_text(), 'clean\nclean\n')
        # Readiness can be retried after fixing the cause, without restarting
        # the daemon or weakening the guard on incoming packages.
        helper.write_text(f'#!/bin/sh\necho "$1" >> "{self.dir / "calls"}"\n')
        path = self.dir / 'test.fwu'; path.write_bytes(b'retry after clean failure')
        self.assertEqual(self.client.verify(path)['state'], 2)
        self.assertEqual((self.dir / 'calls').read_text(), 'clean\nclean\nclean\nverify\n')

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
                            '--board', 'ascent-vrx', '--replace', str(self.dir/'images'), str(path)],
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

    def test_device_info_reports_the_image_version(self):
        """The image's /etc/fpvos-version (scripts/fpvos-version) is the SDK
        field, read at every request; "development" without one."""
        self.assertEqual(self.client.info()['sdk'], 'development')
        (self.bin / 'fpvos-version').write_text('2026.11.beta1+g304b4c79-dirty\n')
        self.assertEqual(self.client.info()['sdk'], '2026.11.beta1+g304b4c79-dirty')
        (self.bin / 'fpvos-version').write_text('2026.11.beta1\n')
        self.assertEqual(self.client.info()['sdk'], '2026.11.beta1')
        (self.bin / 'fpvos-version').write_text('')
        self.assertEqual(self.client.info()['sdk'], 'development')
        (self.bin / 'fpvos-version').write_text('x' * 80)
        self.assertEqual(self.client.info()['sdk'], 'x' * 31)

    def test_oversized_frame_disconnects_without_allocation(self):
        h = bytearray(CLIENT.packet(0x74))
        struct.pack_into('<I', h, 20, 0x7fffffff)
        os.write(self.master, h)
        self.process.wait(timeout=2)
        self.assertFalse((self.dir / 'stage/package.fwu').exists())

    def test_clean_abandons_an_upload_interrupted_between_chunks(self):
        """The host lost the upload between chunks and starts over: its clean
        (sent before any READY) drops the partial transfer instead of being
        refused as "transfer active" until a power cycle."""
        self.start(b'abcd')
        self.client.ack(0x74, b'ab')
        self.assertFalse(self.client.clean())
        self.assertFalse((self.dir / 'stage/package.fwu').exists())
        with self.assertRaisesRegex(ValueError, 'invalid command or state'):
            self.client.ack(0x74, b'cd')
        path = self.dir / 'test.fwu'; path.write_bytes(b'after an interrupted upload')
        self.assertEqual(self.client.verify(path)['state'], 2)
        self.assertEqual((self.dir / 'calls').read_text(), 'clean\nclean\nclean\nverify\n')

    def test_idle_upload_is_abandoned(self):
        """No chunk for the idle time (1 s in this build, 60 s on a unit): the
        transfer goes, and reboot is no longer refused."""
        self.restart('idle')
        self.start(b'abcd')
        self.client.ack(0x74, b'ab')
        time.sleep(0.5)
        self.client.ack(0x74, b'c')  # data keeps it alive
        time.sleep(0.7)
        self.assertEqual(self.client.info()['detail'], 'receiving')
        time.sleep(1.8)
        self.assertEqual(self.client.info()['detail'], 'clean RAM mode')
        self.assertFalse((self.dir / 'stage/package.fwu').exists())
        with self.assertRaisesRegex(ValueError, 'invalid command or state'):
            self.client.ack(0x74, b'd')
        self.client.ack(3, b'reboot'.ljust(32, b'\0'))
        self.wait_calls('clean\nreboot\n')

    def test_status_written_just_before_the_installer_exits_is_seen(self):
        """The worker reaped first, its status read after: with the two far
        apart (this build), an install that writes "100 4" and exits at once is
        still a success."""
        self.restart('gap')
        status = self.dir / 'stage/status'
        (self.dir / 'helper').write_text(
            f'#!/bin/sh\nif [ "$1" = install ]; then\nsleep .05\necho "100 4 installed" > "{status}"\nfi\n')
        path = self.dir / 'test.fwu'; path.write_bytes(b'quick installer')
        result = self.client.verify(path, install=True)
        self.assertEqual((result['state'], result['progress']), (4, 100))

    def test_installer_killed_while_writing_blocks_reboot(self):
        """Killed by a signal while it reported writing (3): the kernel/DTB may
        be half written and the RAM backups go with a reboot, so the reboot is
        blocked (-2), after a receiver restart too. Killed before it reported
        anything is an ordinary failure."""
        status = self.dir / 'stage/status'
        helper = self.dir / 'helper'
        path = self.dir / 'test.fwu'; path.write_bytes(b'killed installer')
        helper.write_text('#!/bin/sh\n[ "$1" != install ] || kill -KILL $$\n')
        with self.assertRaisesRegex(RuntimeError, r'\(-1\)'):
            self.client.verify(path, install=True)
        self.assertEqual(struct.unpack_from('<Ii', self.client.exchange(0x76))[1], -1)
        helper.write_text(f'#!/bin/sh\nif [ "$1" = install ]; then\n'
                          f'echo "60 3 writing device tree" > "{status}"\nulimit -c 0\nkill -SEGV $$\nfi\n')
        with self.assertRaisesRegex(RuntimeError, r'\(-2\): installer killed while writing'):
            self.client.verify(path, install=True)
        with self.assertRaisesRegex(ValueError, 'blocked'):
            self.client.ack(3, b'reboot'.ljust(32, b'\0'))
        self.restart()
        with self.assertRaisesRegex(ValueError, 'blocked'):
            self.client.ack(3, b'reboot'.ljust(32, b'\0'))
        self.assertEqual(struct.unpack_from('<Ii', self.client.exchange(0x76)), (0, -2))

    def test_completed_install_survives_a_receiver_restart(self):
        """After "100 4" a restart (USB reconnect, respawn) keeps the completed
        install: no startup clean that could fail it into -1."""
        (self.bin / 'clean-boot').touch()
        (self.dir / 'stage/status').write_text('100 4 fpvOS installed; reboot required\n')
        (self.dir / 'helper').write_text(f'#!/bin/sh\necho "$1" >> "{self.dir / "calls"}"\nexit 7\n')
        self.restart()
        body = self.client.exchange(0x76)
        self.assertEqual(struct.unpack_from('<Ii', body), (100, 4))
        self.assertIn(b'fpvOS installed; reboot required', body[8:])
        self.assertEqual(self.client.info()['detail'], 'fpvOS installed; reboot required')
        self.assertFalse((self.dir / 'calls').exists())
        self.client.ack(3, b'reboot'.ljust(32, b'\0'))
        self.wait_calls('reboot\n')

    def test_resent_file_start_must_name_the_same_kind_of_destination(self):
        self.start(b'abcd')
        metadata = lambda destination: struct.pack('<64sii128s128s', hashlib.md5(b'abcd').hexdigest().encode(),
                                                   4, 1, destination.encode(), b'host')
        self.client.ack(0x73, metadata(CLIENT.VERIFY_DESTINATION))
        with self.assertRaisesRegex(ValueError, 'invalid command or state'):
            self.client.ack(0x73, metadata(CLIENT.DESTINATION))
        self.client.ack(0x74, b'abcd')
        self.client.ack(0x75)
        self.assertEqual(struct.unpack_from('<Ii', self.client.exchange(0x76))[1], 2)
        self.assertEqual((self.dir / 'calls').read_text(), 'clean\nverify\n')

    def test_refused_destination_does_not_inherit_an_earlier_install(self):
        """With a board's destination hook, which leaves the flags alone when
        it refuses: an install earlier in the same process does not make a
        refused destination an install."""
        self.restart('hook')
        (self.dir / 'helper').write_text(
            f'#!/bin/sh\nif [ "$1" = install ]; then echo "100 4 installed" > "{self.dir / "stage/status"}"; fi\n')
        path = self.dir / 'test.fwu'; path.write_bytes(b'first install')
        self.assertEqual(self.client.verify(path, install=True)['state'], 4)
        for destination in ('/etc/passwd', '/tmp/pc/other.fwu'):
            with self.assertRaisesRegex(ValueError, 'destination'):
                self.start(b'abcd', destination)
        self.assertFalse((self.dir / 'stage/package.fwu').exists())

    def test_refused_clean_in_normal_mode_keeps_showing_the_usb_mode(self):
        """A backend without clean mode (the VRX Pro's serial one) refuses it:
        the answer says so, and FIND_DEVICE still follows the USB mode."""
        (self.dir / 'helper').write_text(f'#!/bin/sh\necho "$1" >> "{self.dir / "calls"}"\n[ "$1" != clean ] || exit 1\n')
        self.addCleanup((self.bin / 'usb-mode').unlink, missing_ok=True)
        with self.assertRaisesRegex(ValueError, 'clean-mode preparation failed'):
            self.client.clean()
        self.assertEqual(self.client.info()['detail'], 'normal mode')
        self.assertEqual(struct.unpack_from('<Ii', self.client.exchange(0x76)), (0, 0))
        (self.bin / 'usb-mode').write_text('bridge\n')
        self.assertEqual(self.client.info()['detail'], 'bridge mode')

    def test_a_refusal_carries_the_helpers_own_reason(self):
        """The helper's first stderr line is the reply's reason, and its
        whole stderr is kept for fpvos-diag; something it leaves running with
        stderr open does not hold the reply."""
        log = Path('/run/fpvos-update-helper.log')
        (self.dir / 'helper').write_text(
            '#!/bin/sh\n[ "$1" != clean ] || { echo "  GPT 1: no usr_log partition" >&2; echo "P1 preflight failed" >&2; '
            'sleep 20 & exit 1; }\n')
        start = time.monotonic()
        with self.assertRaisesRegex(ValueError, 'GPT 1: no usr_log partition'):
            self.client.clean()
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(self.client.info()['detail'], 'normal mode')
        if log.exists() and os.access(log, os.R_OK):
            self.assertIn('P1 preflight failed', log.read_text())
        # without a reason, the generic one
        (self.dir / 'helper').write_text('#!/bin/sh\n[ "$1" != clean ] || exit 1\n')
        with self.assertRaisesRegex(ValueError, 'clean-mode preparation failed'):
            self.client.clean()

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
