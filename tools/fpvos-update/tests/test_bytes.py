# SPDX-License-Identifier: GPL-2.0-or-later
"""Known wire encodings and CRC vectors, including unaligned and chunked input."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_update import SRC


class ByteHelpers(unittest.TestCase):
    def test_wire_encodings_and_incremental_crc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'vectors.c'
            source.write_text(r"""
#include <assert.h>
#include <string.h>
#include "fpvos-bytes.h"
int main(void)
{
    const unsigned char input[] = "123456789";
    assert(fpvos_crc32(input, 9) == 0xcbf43926U);
    assert(fpvos_crc32(input, 0) == 0);
    for (unsigned int split = 0; split <= 9; split++) {
        unsigned int c = fpvos_crc32_update(~0U, input, split);
        assert(~fpvos_crc32_update(c, input + split, 9 - split) == 0xcbf43926U);
    }
    unsigned char b[10] = {0xa5};
    fpvos_put_le64(b + 1, 0xfedcba9876543210ULL);
    const unsigned char expected[] = {0x10,0x32,0x54,0x76,0x98,0xba,0xdc,0xfe};
    assert(!memcmp(b + 1, expected, 8));
    assert(b[0] == 0xa5 && b[9] == 0);
    assert(fpvos_get_le64(b + 1) == 0xfedcba9876543210ULL);
    assert(fpvos_get_le32(b + 1) == 0x76543210U);
    assert(fpvos_get_be32(b + 1) == 0x10325476U);
    return 0;
}
""")
            binary = root / 'vectors'
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2',
                            '-I'+str(SRC), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
