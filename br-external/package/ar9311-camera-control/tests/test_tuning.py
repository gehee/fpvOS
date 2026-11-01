#!/usr/bin/env python3
"""Exercise the patched source loader using synthetic tuning files, no vendor data.

Usage: test_tuning.py PATH_TO_PACKAGE_BUILD_DIRECTORY
"""
import pathlib
import struct
import subprocess
import sys
import tempfile
import unittest

SOURCE = pathlib.Path(sys.argv.pop(1)).resolve() / 'ml-aed'

class Tuning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = pathlib.Path(cls.tmp.name)
        (cls.root / 'probe.c').write_text('''#include "ml-aed-tuning.h"
#include <stdio.h>
int main(int n, char **v) {
 struct ae_tuning t;
 if (n != 2 || ae_tuning_load(&t, v[1])) return 1;
 printf("%zu\\n", t.table_len); ae_tuning_free(&t); return 0;
}
''')
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-I', str(SOURCE),
                        str(cls.root / 'probe.c'), str(SOURCE / 'ml-aed-tuning.c'),
                        '-lm', '-o', str(cls.root / 'probe')], check=True)

        (cls.root / 'decision.c').write_text('''#include "ml-aed-core.h"
int main(void) {
    struct ae_tuning t = {
        .tolerance = 2, .damping = 70.0f / 256, .log_ladder = 77.894f,
        .curve = {{0,32}, {80,30}, {160,28}, {240,24}, {320,20}},
        .index_min = 1, .index_max = 477
    };
    struct ae_state s = {.exp_index = 317};
    for (int i = 0; i < 100; i++) {
        int old = s.exp_index;
        ae_decide(&t, &s, 0.0f);
        if (s.exp_index < old || s.exp_index > 477) return 1;
    }
    if (s.exp_index != 477) return 2;
    for (int i = 0; i < 100; i++) ae_decide(&t, &s, 255.0f);
    return s.exp_index < 1 || s.exp_index >= 477;
}
''')
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined,float-cast-overflow', '-I', str(SOURCE),
                        str(cls.root / 'decision.c'), str(SOURCE / 'ml-aed-core.c'),
                        '-lm', '-o', str(cls.root / 'decision')], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def fixture(self, count=478):
        b = bytearray(0xd6c58)
        struct.pack_into('<I', b, 0xb6508, count)
        for i in range(min(count, 512)):
            struct.pack_into('<II', b, 0xb6524 + i * 8, 256 + i, 1 + i)
        for i in range(5):
            struct.pack_into('<II', b, 0xba560 + i * 8, i * 80, 32 - i * 2)
        struct.pack_into('<I', b, 0xba5fc, 70)
        struct.pack_into('<I', b, 0xba600, 2)
        struct.pack_into('<f', b, 0xba620, 77.894)
        return b

    def run_blob(self, b, expected=None):
        path = self.root / 'tuning.bin'
        path.write_bytes(b)
        r = subprocess.run([str(self.root / 'probe'), str(path)], capture_output=True)
        if expected is None:
            self.assertNotEqual(r.returncode, 0)
        else:
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(int(r.stdout), expected)

    def test_zero_luma_recovers(self):
        subprocess.run([str(self.root / 'decision')], check=True)

    def test_p1_count(self):
        self.run_blob(self.fixture(), 478)

    def test_reference_count(self):
        self.run_blob(self.fixture(366), 366)

    def test_truncated(self):
        self.run_blob(self.fixture()[:-1])

    def test_empty_count(self):
        self.run_blob(self.fixture(0))

    def test_oversized_count(self):
        self.run_blob(self.fixture(513))

    def test_empty_entry(self):
        b = self.fixture()
        struct.pack_into('<I', b, 0xb6524 + 477 * 8, 0)
        self.run_blob(b)
    def test_invalid_ladder(self):
        b = self.fixture()
        struct.pack_into('<f', b, 0xba620, float('nan'))
        self.run_blob(b)
    def test_invalid_damping(self):
        b = self.fixture()
        struct.pack_into('<I', b, 0xba5fc, 0)
        self.run_blob(b)
    def test_unordered_target(self):
        b = self.fixture()
        struct.pack_into('<I', b, 0xba560 + 8, 0)
        self.run_blob(b)

if __name__ == '__main__':
    unittest.main()
