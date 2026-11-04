#!/usr/bin/env python3
"""Mount guards tested with fake sysfs/UBI and mount commands; no NAND writes."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BOARD = Path(__file__).resolve().parents[1]


class SettingsMount(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        text = (BOARD/'source-rootfs-overlay/etc/init.d/S45settings').read_text()
        for prefix in ('/sys/', '/dev/', '/proc/', '/persist', '/var/lib/'):
            text = text.replace(prefix, str(self.root)+prefix)
        self.script = self.root/'script'
        self.script.write_text(text)
        for k, v in dict(name='usr_data', offset='118489088', size='6291456',
                         erasesize='131072', writesize='2048', flags='0x400').items():
            self.put('sys/class/mtd/mtd4/'+k, v)
        self.put('sys/class/ubi/ubi2/mtd_num', '4')
        self.put('sys/class/ubi/ubi2/ro_mode', '0')
        self.put('sys/class/ubi/ubi2_0/name', 'usrdata')
        self.put('proc/mounts', '')
        self.bin = self.root/'bin'
        self.bin.mkdir()
        for command in ('modprobe', 'mount', 'umount', 'ubiattach', 'sync'):
            code = '#!/bin/sh\necho "${0##*/} $*" >> "$ROOT/calls"\n'
            if command == 'ubiattach':
                code += 'exit 23\n'
            if command == 'mount':
                code += '''[ "${FAIL_MOUNT:-0}" = 0 ] || exit 23
if [ "$1" = --bind ]; then
    rmdir "$3" || exit 1
    # Simulate the bind's inode identity without a privileged host mount.
    ln -s "$2" "$3" || exit 1
    echo "$ROOT/dev/ubi2_0 $3 ubifs rw,nodev,nosuid,noexec 0 0" >> "$ROOT/proc/mounts"
else
    echo "$ROOT/dev/ubi2_0 $6 ubifs rw,nodev,nosuid,noexec 0 0" >> "$ROOT/proc/mounts"
fi
'''
            p = self.bin/command
            p.write_text(code)
            p.chmod(0o755)

    def put(self, name, text):
        p = self.root/name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text+'\n')

    def run_start(self, **env):
        r = subprocess.run(['sh', str(self.script), 'start'], capture_output=True, text=True,
                           env={**os.environ, 'PATH': str(self.bin)+':'+os.environ['PATH'],
                                'ROOT': str(self.root), **env})
        calls = self.root/'calls'
        return r, calls.read_text() if calls.exists() else ''

    def test_existing_volume_preserves_vendor_files(self):
        self.put('persist/lowdelay/vendor.json', '{"keep":1}')
        r, calls = self.run_start()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('rw,nodev,nosuid,noexec', calls)
        self.assertIn('mount --bind ', calls)
        self.assertEqual((self.root/'persist/lowdelay/vendor.json').read_text(), '{"keep":1}\n')
        self.assertEqual((self.root/'persist/fpvos/kestrel-air').stat().st_mode & 0o777, 0o700)
        self.assertNotIn('ubiattach', calls)

    def test_geometry_and_readonly_mtd_rejected_before_attach(self):
        for name, value in [('offset','0'), ('size','1'), ('erasesize','4096'),
                            ('writesize','4096'), ('flags','0')]:
            with self.subTest(name=name):
                path = self.root/('sys/class/mtd/mtd4/'+name)
                old = path.read_text()
                path.write_text(value)
                r, calls = self.run_start()
                self.assertNotEqual(r.returncode, 0)
                self.assertNotIn('ubiattach', calls)
                self.assertNotIn('mount ', calls)
                path.write_text(old)

    def test_ambiguous_partition(self):
        self.put('sys/class/mtd/mtd5/name', 'usr_data')
        self.assertNotEqual(self.run_start()[0].returncode, 0)

    def test_readonly_ubi(self):
        self.put('sys/class/ubi/ubi2/ro_mode', '1')
        r, calls = self.run_start()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('mount ', calls)

    def test_missing_or_duplicate_volume(self):
        self.put('sys/class/ubi/ubi2_0/name', 'factory')
        self.assertNotEqual(self.run_start()[0].returncode, 0)
        self.put('sys/class/ubi/ubi2_0/name', 'usrdata')
        self.put('sys/class/ubi/ubi2_1/name', 'usrdata')
        self.assertNotEqual(self.run_start()[0].returncode, 0)

    def test_attach_failure_does_not_format(self):
        self.put('sys/class/ubi/ubi2/mtd_num', '9')
        r, calls = self.run_start()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(calls.count('ubiattach '), 1)
        self.assertNotIn('format', calls)
        self.assertNotIn('mount ', calls)

    def test_mount_failure_never_publishes_settings(self):
        r, calls = self.run_start(FAIL_MOUNT='1')
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('mount --bind', calls)
        self.assertFalse((self.root/'persist/fpvos').exists())

    def test_wrong_existing_mount(self):
        self.put('proc/mounts', f'/dev/other {self.root}/persist ubifs rw 0 0')
        r, calls = self.run_start()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('mount --bind', calls)

    def test_symlink_cannot_redirect_settings(self):
        dest = self.root/'persist/fpvos'
        dest.parent.mkdir()
        dest.symlink_to(self.root/'elsewhere')
        r, calls = self.run_start()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('mount --bind', calls)
        self.assertFalse((self.root/'elsewhere').exists())

    def test_ram_settings_not_silently_hidden(self):
        self.put('var/lib/kestrel-air/peer.json', '{}')
        r, calls = self.run_start()
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn('mount --bind', calls)

    def run_launcher(self, mounts):
        repo = BOARD.parents[2]
        text = (repo/'br-external/package/kestrel-air/ar9311-run').read_text()
        config = self.root/'kestrel-defaults'
        config.write_text(f'STATE_DIR={self.root}/state\nPERSISTENT_STATE=1\n')
        camera = self.root/'camera-defaults'
        camera.write_text('SENSOR_MODULE=s TUNING=t WB_RED=1 WB_BLUE=1 WB_STATS_ORDER=o\n')
        (self.root/'proc').mkdir(exist_ok=True)
        (self.root/'proc/mounts').write_text(mounts)
        text = text.replace('/etc/default/kestrel-air', str(config))
        text = text.replace('/etc/default/ar9311-camera', str(camera))
        text = text.replace('/proc/mounts', str(self.root/'proc/mounts'))
        text = text.replace('/dev/kmsg', str(self.root/'kmsg'))
        launcher = self.root/'launcher'
        launcher.write_text(text)
        # Stops at the radio check (no /dev/arlink0 here), past the settings one.
        return subprocess.run(['sh', str(launcher)], capture_output=True, text=True)

    def test_launcher_starts_on_ram_defaults_without_persistent_mount(self):
        r = self.run_launcher('')
        self.assertIn('WARNING: persistent settings unavailable', r.stderr)
        self.assertIn('changes are not saved', (self.root/'kmsg').read_text())
        self.assertIn('Start/provision the radio first', r.stderr)

    def test_launcher_uses_mounted_settings_quietly(self):
        r = self.run_launcher(f'ubi0:usrdata {self.root}/state ubifs rw,relatime 0 0\n')
        self.assertNotIn('WARNING', r.stderr)
        self.assertFalse((self.root/'kmsg').exists())
        self.assertIn('Start/provision the radio first', r.stderr)


if __name__ == '__main__':
    unittest.main()
