#!/usr/bin/env python3
"""Exercise factory startup guards with isolated sysfs fixtures and no devices."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'source-rootfs-overlay/etc/init.d/S43factory'


class FactoryMount(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.calls = self.root / 'calls'
        # Only the test copy substitutes paths; production has no bypass flags.
        text = SCRIPT.read_text()
        for prefix in ('/sys/', '/dev/', '/proc/', '/factory'):
            text = text.replace(prefix, str(self.root) + prefix)
        self.script = self.root / 'start'
        self.script.write_text(text)
        for key, value in {'name': 'factory', 'offset': '2097152', 'size': '6291456',
                           'erasesize': '131072', 'writesize': '2048', 'flags': '0x0'}.items():
            self.put('sys/class/mtd/mtd3/' + key, value)
        self.put('sys/class/ubi/ubi2/mtd_num', '3')
        self.put('sys/class/ubi/ubi2/ro_mode', '1')
        self.put('sys/class/ubi/ubi2_0/name', 'factory')
        self.put('proc/mounts', '')
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for command in ('modprobe', 'mount', 'umount', 'ubiattach'):
            p = self.bin / command
            p.write_text('#!/bin/sh\nprintf "%s %s\\n" "${0##*/}" "$*" >> "$CALLS"\n' +
                         ('exit 23\n' if command == 'ubiattach' else 'exit 0\n'))
            p.chmod(0o755)

    def put(self, path, value):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value + '\n')

    def run_start(self):
        r = subprocess.run(['sh', str(self.script), 'start'], capture_output=True, text=True,
                           env={**os.environ, 'PATH': str(self.bin) + ':' + os.environ['PATH'],
                                'CALLS': str(self.calls)})
        calls = self.calls.read_text() if self.calls.exists() else ''
        return r, calls

    def rejected(self):
        r, calls = self.run_start()
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertNotIn('\nmount ', '\n' + calls)
        return calls

    def test_readonly_existing_ubi_uses_discovered_indices(self):
        r, calls = self.run_start()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('mount -t ubifs -o ro,nodev,nosuid,noexec ', calls)
        self.assertIn('/dev/ubi2_0 ', calls)
        self.assertNotIn('ubiattach', calls)

    def test_existing_readonly_mount_still_checks_ubi_protection(self):
        self.put('proc/mounts', f'{self.root}/dev/ubi2_0 {self.root}/factory ubifs ro 0 0')
        self.put('sys/class/ubi/ubi2/ro_mode', '0')
        self.rejected()

    def test_existing_expected_readonly_mount_is_idempotent(self):
        self.put('proc/mounts', f'{self.root}/dev/ubi2_0 {self.root}/factory ubifs ro 0 0')
        r, calls = self.run_start()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('\nmount ', '\n' + calls)

    def test_writable_mtd_never_attaches(self):
        self.put('sys/class/mtd/mtd3/flags', '0x400')
        self.assertNotIn('ubiattach', self.rejected())

    def test_wrong_partition_offset(self):
        self.put('sys/class/mtd/mtd3/offset', '0')
        self.assertNotIn('ubiattach', self.rejected())

    def test_ambiguous_partition(self):
        self.put('sys/class/mtd/mtd4/name', 'factory')
        self.rejected()

    def test_writable_ubi_rejected(self):
        self.put('sys/class/ubi/ubi2/ro_mode', '0')
        self.rejected()

    def test_missing_factory_volume_rejected(self):
        self.put('sys/class/ubi/ubi2_0/name', 'wrong-volume')
        self.rejected()

    def test_attach_failure_has_no_repair_fallback(self):
        self.put('sys/class/ubi/ubi2/mtd_num', '9')
        calls = self.rejected()
        self.assertEqual(calls.count('ubiattach '), 1)
        self.assertNotIn('format', calls)

    def test_existing_writable_mount_rejected(self):
        self.put('proc/mounts', f'/dev/ubi2_0 {self.root}/factory ubifs rw 0 0')
        self.rejected()


if __name__ == '__main__':
    unittest.main()
