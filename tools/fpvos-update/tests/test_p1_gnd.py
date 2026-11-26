# SPDX-License-Identifier: GPL-2.0-or-later
"""The P1 ground units (goggles and Nano VRX, one backend) use the shared P1
backend with the bank chosen per unit and whichever matched U-Boot pair the
unit uses, as the P1 Air does."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_p1 as p1
from test_p1 import ROOT


class P1GndTests(p1.P1Tests):
    config_flags = ['-include', str(ROOT / 'br-external/package/fpvos-update/backends/p1-gnd/config.h')]
    kernel_name = b'fpvOS P1 ground recovery'


# The image policy's device-tree rule alone: libfdt stands in as a root
# compatible list kept as plain strings after a 40-byte header.
FDT_STUB = r"""
#include <stddef.h>
#include <string.h>
static inline int fdt_check_full(const void *d, size_t n) { (void)d; return n < 40; }
static inline size_t fdt_totalsize(const void *d) { return 40 + strlen((const char *)d + 40) + 1 + strlen((const char *)d + 40 + strlen((const char *)d + 40) + 1) + 1; }
static inline int fdt_node_check_compatible(const void *d, int node, const char *c)
{
    const char *first = (const char *)d + 40, *second = first + strlen(first) + 1;
    (void)node;
    return strcmp(first, c) && strcmp(second, c);
}
"""
MAIN = r"""
#include "board.h"
#include <stdio.h>
int main(int argc, char **argv)
{
    static unsigned char b[4096];
    FILE *f = argc == 2 ? fopen(argv[1], "rb") : NULL;
    if (!f) return 2;
    size_t n = fread(b, 1, sizeof(b), f);
    fclose(f);
    return !fpvos_board_image_valid(1, b, n, 0);
}
"""


def tree(*compatible):
    return bytes(40) + b''.join(c.encode() + b'\0' for c in compatible)


class UnitTree(unittest.TestCase):
    """A bundle's device tree is taken only by the unit it is for."""
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.d = Path(cls.temp.name)
        (cls.d / 'libfdt.h').write_text(FDT_STUB)
        (cls.d / 'main.c').write_text(MAIN)
        pkg = ROOT / 'br-external/package/fpvos-update'
        subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-I' + str(cls.d), '-I' + str(pkg / 'src'),
                        '-DP1_UNIT_TREE="unit"', str(pkg / 'backends/p1-gnd/images.c'), str(cls.d / 'main.c'), '-o', str(cls.d / 'valid')], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def valid(self, unit, *bundle):
        """Whether a unit whose tree says UNIT takes a bundle tree BUNDLE."""
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            if unit is not None:
                (d / 'unit').write_bytes(b''.join(c.encode() + b'\0' for c in unit))
            (d / 'dtb').write_bytes(tree(*bundle))
            return subprocess.run([str(self.d / 'valid'), 'dtb'], cwd=d).returncode == 0

    GOGGLES = ('betafpv,p1-goggle', 'artosyn,proxima-9311')
    NANO = ('betafpv,p1-nano-vrx', 'artosyn,proxima-9311')
    PRO = ('betafpv,p1-goggle-pro', 'artosyn,proxima-9311')
    UNITS = (GOGGLES, NANO, PRO)

    def test_each_unit_takes_its_own_tree(self):
        for unit in self.UNITS:
            self.assertTrue(self.valid(unit, *unit), unit)

    def test_the_other_units_tree_is_refused(self):
        for unit in self.UNITS:
            for other in self.UNITS:
                if other is not unit:
                    self.assertFalse(self.valid(unit, *other), (unit, other))

    def test_no_tree_without_a_known_unit(self):
        for unit in (None, (), ('betafpv,p1-air', 'artosyn,proxima-9311'), ('artosyn,proxima-9311',)):
            for bundle in self.UNITS:
                self.assertFalse(self.valid(unit, *bundle), (unit, bundle))

    def test_a_stock_units_recovery_takes_any_units_tree(self):
        """It runs on the tree of any ground unit: the bundle chosen names the unit."""
        recovery = ('betafpv,p1-gnd', 'artosyn,proxima-9311')
        for unit in self.UNITS:
            self.assertTrue(self.valid(recovery, *unit), unit)
        self.assertFalse(self.valid(recovery, 'betafpv,p1-air', 'artosyn,proxima-9311'))
        self.assertFalse(self.valid(recovery, *recovery))       # never installed itself

    def test_another_boards_tree_is_refused(self):
        self.assertFalse(self.valid(self.GOGGLES, 'betafpv,p1-air', 'artosyn,proxima-9311'))
        self.assertFalse(self.valid(self.GOGGLES, 'artosyn,proxima-9311', 'x'))


del p1  # only this module's own tests are collected from it

if __name__ == '__main__': unittest.main()
