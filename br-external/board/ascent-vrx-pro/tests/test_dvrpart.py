#!/usr/bin/env python3
"""S35dvrpart formats the recordings partition only when it is positively not
exFAT: an exFAT filesystem exfatlabel or mount cannot read is repaired or left
alone, never formatted."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

BOARD = Path(__file__).resolve().parents[1]
SCRIPT = BOARD / 'rootfs-overlay/etc/init.d/S35dvrpart'
SYSTEM_PATH = '/usr/sbin:/sbin:/usr/bin:/bin'

# Stand-ins, each logging its name and arguments. The behaviour comes from the
# environment: EXFATLABEL=ok|fail|fail-once (LABEL is what it reports),
# FSCK_RC, MOUNT=ok|fail|fail-once.
STANDINS = {
    'exfatlabel': r'''#!/bin/sh
echo "exfatlabel $*" >> "$LOG"
case $EXFATLABEL in
    fail) exit 1 ;;
    fail-once) [ -e "$LOG.exfatlabel" ] || { touch "$LOG.exfatlabel"; exit 1; } ;;
esac
[ $# -eq 2 ] && exit 0
echo "exfatprogs version : 1.2.9"
echo "label: $LABEL"
''',
    'mkfs.exfat': '#!/bin/sh\necho "mkfs.exfat $*" >> "$LOG"\n',
    'fsck.exfat': '#!/bin/sh\necho "fsck.exfat $*" >> "$LOG"\nexit ${FSCK_RC:-0}\n',
    'mount': r'''#!/bin/sh
echo "mount $*" >> "$LOG"
case $MOUNT in
    fail) exit 32 ;;
    fail-once) [ -e "$LOG.mount" ] || { touch "$LOG.mount"; exit 32; } ;;
esac
exit 0
''',
}

BOOT_SECTOR = b'\xebv\x90EXFAT   ' + bytes(512 - 11)


def functions(text, *names):
    return ''.join(re.search(rf'^{n}\(\) \{{\n.*?^\}}\n', text, re.S | re.M).group(0) for n in names)


class Prepare(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.d = Path(temp.name)
        self.bin = self.d / 'bin'; self.bin.mkdir()
        body = functions(SCRIPT.read_text(), 'exfat_at', 'repair', 'prepare')
        (self.d / 'prepare.sh').write_text(f'PART="$1"\nMNT="$2"\n{body}prepare\n')
        self.img = self.d / 'p4.img'
        self.log = self.d / 'log'

    def standins(self, *names):
        for n in names:
            p = self.bin / n; p.write_text(STANDINS[n]); p.chmod(0o755)

    def image(self, size=1 << 20, at=()):
        data = bytearray(size)
        for sector in at:
            data[sector * 512:sector * 512 + 512] = BOOT_SECTOR
        self.img.write_bytes(bytes(data))

    def run_prepare(self, **env):
        e = dict(os.environ, PATH=f'{self.bin}:{SYSTEM_PATH}', LOG=str(self.log), **{'LABEL': 'dvr', **env})
        r = subprocess.run(['sh', str(self.d / 'prepare.sh'), str(self.img), str(self.d / 'mnt')],
                           env=e, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.out = r.stdout
        return self.log.read_text().splitlines() if self.log.exists() else []

    def assertNotFormatted(self, calls):
        self.assertFalse([c for c in calls if c.startswith('mkfs.exfat')], calls)

    # --- not exFAT: formatted -------------------------------------------------

    def test_a_blank_partition_is_formatted_and_mounted(self):
        self.standins('exfatlabel', 'mkfs.exfat', 'fsck.exfat', 'mount')
        self.image()
        calls = self.run_prepare(EXFATLABEL='ok')
        self.assertIn(f'mkfs.exfat -L dvr {self.img}', calls)
        self.assertTrue(calls[-1].startswith('mount -t exfat'), calls)

    def test_another_filesystem_is_formatted(self):
        self.standins('exfatlabel', 'mkfs.exfat', 'fsck.exfat', 'mount')
        data = bytearray(1 << 20)
        data[1080:1082] = b'\x53\xef'                         # ext4's superblock magic
        data[3:11] = b'NTFS    '                              # and an NTFS name, at exFAT's offset
        self.img.write_bytes(bytes(data))
        self.assertIn(f'mkfs.exfat -L dvr {self.img}', self.run_prepare(EXFATLABEL='ok'))

    # --- exFAT: never formatted -----------------------------------------------

    def test_exfat_with_the_right_label_is_just_mounted(self):
        self.standins('exfatlabel', 'mkfs.exfat', 'fsck.exfat', 'mount')
        self.image(at=(0, 12))
        calls = self.run_prepare(EXFATLABEL='ok', LABEL='DVR')
        self.assertNotFormatted(calls)
        self.assertEqual([c.split()[0] for c in calls], ['exfatlabel', 'exfatlabel', 'mount'])

    def test_a_wrong_label_is_corrected_in_place(self):
        self.standins('exfatlabel', 'mkfs.exfat', 'fsck.exfat', 'mount')
        self.image(at=(0, 12))
        calls = self.run_prepare(EXFATLABEL='ok', LABEL='')
        self.assertNotFormatted(calls)
        self.assertIn(f'exfatlabel {self.img} dvr', calls)
        self.assertIn('was: unlabelled', self.out)

    def test_exfat_exfatlabel_cannot_read_is_repaired_not_formatted(self):
        self.standins('exfatlabel', 'mkfs.exfat', 'fsck.exfat', 'mount')
        self.image(at=(0, 12))
        calls = self.run_prepare(EXFATLABEL='fail-once', FSCK_RC='1')
        self.assertNotFormatted(calls)
        self.assertIn(f'fsck.exfat -p {self.img}', calls)
        self.assertTrue(calls[-1].startswith('mount -t exfat'), calls)

    def test_exfat_fsck_cannot_repair_is_left_unmounted(self):
        self.standins('exfatlabel', 'mkfs.exfat', 'fsck.exfat', 'mount')
        self.image(at=(0, 12))
        calls = self.run_prepare(EXFATLABEL='fail', FSCK_RC='4')
        self.assertNotFormatted(calls)
        self.assertFalse([c for c in calls if c.startswith('mount')], calls)
        self.assertIn('left unmounted, not formatted', self.out)

    def test_exfat_without_fsck_is_left_unmounted(self):
        if shutil.which('fsck.exfat', path=SYSTEM_PATH):
            self.skipTest('this host has a real fsck.exfat')
        self.standins('exfatlabel', 'mkfs.exfat', 'mount')
        self.image(at=(0, 12))
        calls = self.run_prepare(EXFATLABEL='fail')
        self.assertNotFormatted(calls)
        self.assertFalse([c for c in calls if c.startswith('mount')], calls)
        self.assertIn('no fsck.exfat', self.out)

    def test_exfat_that_does_not_mount_is_repaired_and_mounted_again(self):
        self.standins('exfatlabel', 'mkfs.exfat', 'fsck.exfat', 'mount')
        self.image(at=(0, 12))
        calls = self.run_prepare(EXFATLABEL='ok', MOUNT='fail-once')
        self.assertNotFormatted(calls)
        self.assertEqual([c.split()[0] for c in calls][-3:], ['mount', 'fsck.exfat', 'mount'])
        self.assertIn('ready', self.out)

    def test_exfat_that_never_mounts_is_left_alone(self):
        self.standins('exfatlabel', 'mkfs.exfat', 'fsck.exfat', 'mount')
        self.image(at=(0, 12))
        calls = self.run_prepare(EXFATLABEL='ok', MOUNT='fail')
        self.assertNotFormatted(calls)
        self.assertIn('left unmounted, not formatted', self.out)

    def test_the_backup_boot_sector_alone_is_enough(self):
        self.standins('exfatlabel', 'mkfs.exfat', 'fsck.exfat', 'mount')
        self.image(at=(12,))                                  # main boot sector wiped
        calls = self.run_prepare(EXFATLABEL='fail', FSCK_RC='1')
        self.assertNotFormatted(calls)
        self.assertIn(f'fsck.exfat -p {self.img}', calls)

    def test_a_partition_that_cannot_be_read_is_left_alone(self):
        self.standins('exfatlabel', 'mkfs.exfat', 'fsck.exfat', 'mount')
        self.image(size=4096)                                 # the backup sector is past the end
        self.assertEqual(self.run_prepare(EXFATLABEL='fail'), [])
        self.assertIn('cannot read', self.out)
        self.img.unlink()                                     # no device at all
        self.assertEqual(self.run_prepare(EXFATLABEL='fail'), [])

    # --- a filesystem made by exfatprogs itself -------------------------------

    def test_a_real_exfat_filesystem(self):
        mkfs = shutil.which('mkfs.exfat', path=SYSTEM_PATH)
        if not (mkfs and shutil.which('exfatlabel', path=SYSTEM_PATH)):
            self.skipTest('exfatprogs not installed on this host')
        self.img.write_bytes(bytes(16 << 20))
        subprocess.run([mkfs, '-L', 'other', str(self.img)], check=True, capture_output=True)
        boot = self.img.read_bytes()[:13 * 512]
        self.assertEqual(boot[3:11], b'EXFAT   ')
        self.assertEqual(boot[12 * 512 + 3:12 * 512 + 11], b'EXFAT   ')
        # The real exfatlabel; a mkfs.exfat that would be logged if called.
        self.standins('mkfs.exfat', 'fsck.exfat', 'mount')
        calls = self.run_prepare()
        self.assertNotFormatted(calls)
        out = subprocess.run(['exfatlabel', str(self.img)], capture_output=True, text=True,
                             env=dict(os.environ, PATH=SYSTEM_PATH)).stdout
        self.assertEqual(out.splitlines()[-1], 'label: dvr')


class Boot(unittest.TestCase):
    def test_phase_two_only_runs_prepare(self):
        start = SCRIPT.read_text().split('case "$1" in', 1)[1]
        self.assertNotIn('mkfs', start)
        self.assertIn('[ -b "$PART" ] && prepare', start)


if __name__ == '__main__':
    unittest.main()
