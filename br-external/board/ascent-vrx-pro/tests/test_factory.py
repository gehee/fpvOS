#!/usr/bin/env python3
"""S50factory reports what really happened to the SD pairing list, and always
detaches UBI and removes its runtime NAND partition on the way out."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

BOARD = Path(__file__).resolve().parents[1]
SCRIPT = BOARD / 'rootfs-overlay/etc/init.d/S50factory'

SD_RING = '{"save_candidate_position":1,"bb_mac_addr_0":["0x01","0x02","0x03","0x04"]}\n'
NAND_RING = '{"save_candidate_position":0,"bb_mac_addr_0":["0x0a","0x0b","0x0c","0x0d"]}\n'

# Stand-ins for the NAND side, logging each call. State lives in files: the
# fake /proc/mtd, the fake /sys/class/ubi, and a "mounted" marker.
STANDINS = {
    'mtdpart': r'''#!/bin/sh
echo "mtdpart $*" >> "$T/calls"
case $1 in
    add) echo "mtd1: 01000000 00020000 \"$3\"" >> "$T/mtd" ;;
    del) grep -v "^mtd$3:" "$T/mtd" > "$T/mtd.new"; mv "$T/mtd.new" "$T/mtd" ;;
esac
''',
    'ubiattach': '#!/bin/sh\necho "ubiattach $*" >> "$T/calls"\n'
                 '[ -z "$FAIL_ATTACH" ] || exit 1\nmkdir -p "$T/ubi/ubi10"\n',
    'ubidetach': '#!/bin/sh\necho "ubidetach $*" >> "$T/calls"\nrmdir "$T/ubi/ubi10"\n',
    'mount': r'''#!/bin/sh
echo "mount $*" >> "$T/calls"
[ -z "$FAIL_MOUNT" ] || exit 32
[ -z "$SIGNAL" ] || kill -TERM $PPID
mkdir -p "$T/mnt"; /bin/cp "$T/nand.json" "$T/mnt/user_cfg.json"; touch "$T/mounted"
''',
    'mountpoint': '#!/bin/sh\n[ -e "$T/mounted" ]\n',
    'umount': '#!/bin/sh\necho "umount $*" >> "$T/calls"\nrm -f "$T/mounted"\n',
    'cp': '#!/bin/sh\n[ -z "$FAIL_CP" ] || exit 1\nexec /bin/cp "$@"\n',
    'mv': '#!/bin/sh\ncase $2 in *.json) [ -z "$FAIL_MV" ] || exit 1 ;; esac\nexec /bin/mv "$@"\n',
}


class Factory(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.d = Path(temp.name)
        (self.d / 'bin').mkdir(); (self.d / 'ubi').mkdir()
        for name, text in STANDINS.items():
            p = self.d / 'bin' / name; p.write_text(text); p.chmod(0o755)
        (self.d / 'mtd').write_text('dev:    size   erasesize  name\nmtd0: 08000000 00020000 "spi-nand0"\n')
        (self.d / 'nand.json').write_text(NAND_RING)
        self.sd = self.d / 'factory/user_cfg.json'
        text = SCRIPT.read_text()
        for real, fake in (('/proc/mtd', self.d / 'mtd'), ('/sys/class/ubi', self.d / 'ubi'),
                           ('MNT=/tmp/nand-factory', f'MNT={self.d}/mnt'),
                           ('SD=/factory/user_cfg.json', f'SD={self.sd}'),
                           ('LOG=/var/log/factory-merge.log', f'LOG={self.d}/merge.log')):
            self.assertIn(str(real).split('=')[0], text)
            text = text.replace(str(real), str(fake))
        # The eraseblock scan reads /dev/mtdN; here every block is UBI.
        text = text.replace('\nstart() {', '\nall_ubi() { return 0; }\nstart() {', 1)
        self.script = self.d / 'S50factory'
        self.script.write_text(text)

    def run_start(self, **env):
        e = dict(os.environ, PATH=f'{self.d}/bin:/usr/bin:/bin', T=str(self.d), **env)
        r = subprocess.run(['sh', str(self.script), 'start'], env=e, capture_output=True, text=True)
        self.out = r.stdout
        self.calls = (self.d / 'calls').read_text().splitlines() if (self.d / 'calls').exists() else []
        return r.returncode

    def assertCleanedUp(self):
        self.assertNotIn('fpvos-factory', (self.d / 'mtd').read_text(), self.calls)
        self.assertFalse((self.d / 'ubi/ubi10').exists(), self.calls)
        self.assertFalse((self.d / 'mounted').exists(), self.calls)
        self.assertFalse(self.sd.with_suffix('.json.new').exists())

    def test_copies_stock_list_when_there_is_none(self):
        self.assertEqual(self.run_start(), 0)
        self.assertEqual(self.sd.read_text(), NAND_RING)
        self.assertIn("copied stock's", self.out)
        self.assertCleanedUp()

    def test_a_failed_copy_is_not_reported_as_copied(self):
        self.assertEqual(self.run_start(FAIL_CP='1'), 0)
        self.assertFalse(self.sd.exists())
        self.assertNotIn("copied stock's", self.out)
        self.assertIn('copying stock\'s failed', self.out)
        self.assertCleanedUp()

    def test_merges_into_the_sd_list(self):
        self.sd.parent.mkdir(); self.sd.write_text(SD_RING)
        self.assertEqual(self.run_start(), 0)
        self.assertIn('0x0A', self.sd.read_text())
        self.assertIn("merged stock's pairings", self.out)
        self.assertCleanedUp()

    def test_a_failed_write_of_the_merge_is_not_reported_as_merged(self):
        self.sd.parent.mkdir(); self.sd.write_text(SD_RING)
        self.assertEqual(self.run_start(FAIL_MV='1'), 0)
        self.assertEqual(self.sd.read_text(), SD_RING)
        self.assertNotIn('merged stock', self.out)
        self.assertIn('left as it was', self.out)
        self.assertCleanedUp()

    def test_cleanup_after_a_failed_mount(self):
        self.assertEqual(self.run_start(FAIL_MOUNT='1'), 0)
        self.assertIn('mount failed', self.out)
        self.assertIn('ubidetach -d 10', self.calls)
        self.assertCleanedUp()

    def test_cleanup_after_a_failed_attach(self):
        self.assertEqual(self.run_start(FAIL_ATTACH='1'), 0)
        self.assertIn('mtdpart del /dev/mtd0 1', self.calls)
        self.assertCleanedUp()

    def test_cleanup_when_killed(self):
        self.assertNotEqual(self.run_start(SIGNAL='1'), 0)
        self.assertFalse(self.sd.exists())
        self.assertIn('umount', ' '.join(self.calls))
        self.assertCleanedUp()


if __name__ == '__main__':
    unittest.main()
