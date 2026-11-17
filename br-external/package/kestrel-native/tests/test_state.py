"""Exercise the state hook with an isolated filesystem and fake mount commands."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HOOK = Path(__file__).resolve().parents[1] / 'S46kestrel-state-ubifs'


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('proc', 'sys/class/ubi/ubi0_0', 'sys/class/ubi/ubi0',
                     'sys/class/mtd/mtd11', 'bin', 'var/lib', 'persist', 'etc/default', 'dev'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.write('proc/mounts', '')
        self.write('etc/default/kestrel-state', 'STATE_PARTITION=usr_data\nSTATE_SIZE=6291456\nSTATE_VOLUMES="usrdata usr_data"\n')
        self.write('sys/class/ubi/ubi0_0/name', 'usrdata')
        self.write('sys/class/ubi/ubi0/ro_mode', '0')
        self.write('sys/class/ubi/ubi0/mtd_num', '11')
        self.write('sys/class/mtd/mtd11/name', 'usr_data')
        self.write('sys/class/mtd/mtd11/size', '6291456')
        script = HOOK.read_text()
        for prefix in ('/persist', '/run', '/var', '/sys', '/proc', '/dev', '/mnt', '/etc'):
            script = script.replace(prefix, str(self.root) + prefix)
        self.write('hook', script)
        self.write('bin/mount', '#!/bin/sh\necho "$5 $6 ubifs rw,nodev,nosuid,noexec 0 0" > "$TEST_ROOT/proc/mounts"\n')
        self.write('bin/umount', '#!/bin/sh\n: > "$TEST_ROOT/proc/mounts"\n')
        self.write('bin/mountpoint', '#!/bin/sh\nexit 1\n')
        self.write('bin/sync', '#!/bin/sh\nexit 0\n')
        for path in (self.root / 'bin').iterdir():
            path.chmod(0o755)

    def write(self, path, value):
        (self.root / path).write_text(value)

    def run_hook(self, action='start', success=True):
        result = subprocess.run(['sh', str(self.root / 'hook'), action],
                                env={**os.environ, 'TEST_ROOT': str(self.root),
                                     'PATH': str(self.root / 'bin') + ':' + os.environ['PATH']},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, success, result.stderr)
        return result

    def test_both_volume_names_persist_and_stop(self):
        for name in ('usrdata', 'usr_data'):
            self.write('sys/class/ubi/ubi0_0/name', name)
            self.run_hook()
            state = self.root / 'var/lib/kestrel'
            self.assertEqual(state.resolve(), self.root / 'persist/fpvos/kestrel')
            (state / 'peer').write_text('01:02:03:04\n05:06:07:08\n')
            self.run_hook('stop')
            self.assertEqual(state.resolve(), self.root / 'run/kestrel-state')
            self.assertEqual((self.root / 'proc/mounts').read_text(), '')
            self.run_hook()
            self.assertEqual((state / 'peer').read_text(), '01:02:03:04\n05:06:07:08\n')

    def test_wrong_partition_falls_back_without_mounting(self):
        self.write('sys/class/mtd/mtd11/name', 'factory')
        result = self.run_hook()
        self.assertIn('temporary', result.stderr)
        self.assertEqual((self.root / 'proc/mounts').read_text(), '')
        self.assertEqual((self.root / 'var/lib/kestrel').resolve(), self.root / 'run/kestrel-state')

    def test_ascent_existing_volume_and_sd_ignored(self):
        self.write('etc/default/kestrel-state',
                   'STATE_PARTITION=fpv_data\nSTATE_SIZE=23068672\nSTATE_VOLUMES=fpv_data\n')
        self.write('sys/class/mtd/mtd11/name', 'fpv_data')
        self.write('sys/class/mtd/mtd11/size', '23068672')
        self.write('sys/class/ubi/ubi0_0/name', 'fpv_data')
        old = self.root / 'mnt/sd/fpvos/kestrel'
        old.mkdir(parents=True)
        (old / 'peer').write_text('OLD SD PAIRING')
        self.run_hook()
        self.assertFalse((self.root / 'var/lib/kestrel/peer').exists())
        self.assertEqual((old / 'peer').read_text(), 'OLD SD PAIRING')

    def test_blank_partition_not_attached(self):
        self.write('sys/class/ubi/ubi0/mtd_num', '12')
        self.write('dev/mtd11', 'xxxx')
        result = self.run_hook()
        self.assertIn('temporary', result.stderr)
        self.assertFalse((self.root / 'run/kestrel-state-attached').exists())

    def test_attach_existing_ubi_and_detach_only_owned(self):
        self.write('sys/class/ubi/ubi0/mtd_num', '12')
        self.write('dev/mtd11', 'UBI#')
        self.write('bin/ubiattach', '#!/bin/sh\n[ "$1" = -m ] && [ "$3" = "$TEST_ROOT/dev/ubi_ctrl" ] || exit 2\necho "$2" > "$TEST_ROOT/sys/class/ubi/ubi0/mtd_num"\n')
        self.write('bin/ubidetach', '#!/bin/sh\n[ "$1" = -d ] && [ "$2" = 0 ] && [ "$3" = "$TEST_ROOT/dev/ubi_ctrl" ] || exit 2\necho detached > "$TEST_ROOT/detached"\n')
        for name in ('ubiattach', 'ubidetach'):
            (self.root / 'bin' / name).chmod(0o755)
        self.run_hook()
        self.assertTrue((self.root / 'run/kestrel-state-attached').exists())
        self.assertEqual((self.root / 'var/lib/kestrel').resolve(), self.root / 'persist/fpvos/kestrel')
        self.run_hook('stop')
        self.assertTrue((self.root / 'detached').exists())
        self.assertFalse((self.root / 'run/kestrel-state-attached').exists())

    def test_readonly_ubi_falls_back(self):
        self.write('sys/class/ubi/ubi0/ro_mode', '1')
        self.run_hook()
        self.assertEqual((self.root / 'proc/mounts').read_text(), '')
        self.assertEqual((self.root / 'var/lib/kestrel').resolve(), self.root / 'run/kestrel-state')

    def test_vendor_files_untouched(self):
        self.write('persist/vendor.cfg', 'factory settings')
        self.run_hook()
        self.assertEqual((self.root / 'persist/vendor.cfg').read_text(), 'factory settings')

    def test_existing_ram_directory_is_not_silently_nested(self):
        (self.root / 'var/lib/kestrel').mkdir()
        self.write('var/lib/kestrel/peer', '01:02:03:04\n')
        self.run_hook(success=False)
        self.assertFalse((self.root / 'var/lib/kestrel/kestrel').exists())
        self.assertEqual((self.root / 'var/lib/kestrel/peer').read_text(), '01:02:03:04\n')


if __name__ == '__main__':
    unittest.main()
