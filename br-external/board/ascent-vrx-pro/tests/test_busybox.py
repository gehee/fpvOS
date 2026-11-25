#!/usr/bin/env python3
"""No busybox applet that erases or writes the NAND is in the image, and
nothing in the overlay needs one."""
from pathlib import Path
import os
import re
import unittest

BOARD = Path(__file__).resolve().parents[1]
ROOT = BOARD.parents[2]
FRAGMENT = BOARD / 'busybox.fragment'
# Buildroot's base configuration (the buildroot submodule; BUSYBOX_CONFIG
# names another copy).
BASE = Path(os.environ.get('BUSYBOX_CONFIG', ROOT / 'buildroot/package/busybox/busybox.config'))

# busybox's MTD/UBI writers, by config symbol and applet name.
NAND_WRITERS = {
    'FLASH_ERASEALL': 'flash_eraseall', 'FLASH_LOCK': 'flash_lock', 'FLASH_UNLOCK': 'flash_unlock',
    'FLASHCP': 'flashcp', 'NANDWRITE': 'nandwrite', 'UBIMKVOL': 'ubimkvol', 'UBIRMVOL': 'ubirmvol',
    'UBIRSVOL': 'ubirsvol', 'UBIUPDATEVOL': 'ubiupdatevol', 'UBIRENAME': 'ubirename',
}


def config(text):
    out = {}
    for line in text.splitlines():
        if m := re.match(r'^CONFIG_(\w+)=(.*)$', line):
            out[m.group(1)] = m.group(2)
        elif m := re.match(r'^# CONFIG_(\w+) is not set$', line):
            out[m.group(1)] = 'n'
    return out


class NandWriters(unittest.TestCase):
    def test_the_fragment_turns_ubirename_off(self):
        self.assertEqual(config(FRAGMENT.read_text()).get('UBIRENAME'), 'n')

    def test_none_left_on_after_the_fragment(self):
        if not BASE.is_file():
            self.skipTest(f'no {BASE} (buildroot submodule not checked out)')
        merged = {**config(BASE.read_text()), **config(FRAGMENT.read_text())}
        self.assertEqual([s for s in NAND_WRITERS if merged.get(s, 'n') != 'n'], [])

    def test_the_overlay_calls_none(self):
        files = [BOARD / 'post-build.sh'] + [p for p in (BOARD / 'rootfs-overlay').rglob('*')
                                             if p.is_file() and p.read_bytes()[:2] == b'#!']
        for p in files:
            code = '\n'.join(l for l in p.read_text().splitlines() if not l.lstrip().startswith('#'))
            for applet in NAND_WRITERS.values():
                self.assertNotRegex(code, rf'\b{applet}\b', p)


if __name__ == '__main__':
    unittest.main()
