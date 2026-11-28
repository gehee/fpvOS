#!/usr/bin/env python3
"""The Gnd485 stock-root assembly (backends/ascent-vrx/stock-root.h): UBI
volume 0 of a stock bank, cut at the SquashFS's bytes_used, as the Flasher
fingerprints Caddx's image."""
import os
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[2] / 'br-external/package/fpvos-update/src'
PEB, VID, DATA = 0x20000, 2048, 4096
LEB = PEB - DATA


def crc(h):
    return struct.pack('>I', zlib.crc32(h[:60]) ^ 0xffffffff)


def peb(vol=None, lnum=0, sqnum=0, data=b''):
    """An eraseblock: its EC header, and a VID header and data when VOL is set."""
    block = bytearray(b'\xff' * PEB)
    ec = bytearray(64)
    ec[:5] = b'UBI#\x01'
    struct.pack_into('>QII', ec, 8, 1, VID, DATA)
    ec[60:] = crc(ec)
    block[:64] = ec
    if vol is not None:
        v = bytearray(64)
        v[:5] = b'UBI!\x01'
        v[5] = 1
        struct.pack_into('>IIQ', v, 8, vol, lnum, 0)
        struct.pack_into('>Q', v, 24, sqnum)
        v[60:] = crc(v)
        block[VID:VID + 64] = v
        block[DATA:DATA + len(data)] = data
    return bytes(block)


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.sim = Path(cls.dir.name) / 'stock_root_sim'
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', '-I' + str(SRC), str(HERE / 'stock_root_sim.c'),
                        '-o', str(cls.sim)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def run_sim(self, blocks, bad=None):
        bank = Path(self.dir.name) / 'bank'
        out = Path(self.dir.name) / 'out'
        bank.write_bytes(b''.join(blocks))
        args = [str(self.sim), str(bank), str(out)] + ([str(bad)] if bad is not None else [])
        r = subprocess.run(args, capture_output=True, text=True)
        return r.returncode, out.read_bytes() if out.exists() else b'', r.stderr

    def squashfs(self, size):
        fs = bytearray(os.urandom(size))
        fs[:4] = b'hsqs'
        struct.pack_into('<Q', fs, 40, size)
        return bytes(fs)

    def test_volume_zero_in_order_cut_at_bytes_used(self):
        fs = self.squashfs(LEB * 2 + 1000)
        parts = [fs[i:i + LEB] for i in range(0, len(fs), LEB)]
        blocks = [peb(0, 2, 3, parts[2]), peb(), b'\xff' * PEB, peb(1, 0, 4, b'other volume'),
                  peb(0, 0, 1, parts[0]), peb(0, 1, 2, b'stale copy'), peb(0, 1, 9, parts[1]),
                  b'\xff' * PEB]
        code, out, err = self.run_sim(blocks)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, fs)

    def test_bad_block_skipped_missing_block_refused(self):
        fs = self.squashfs(LEB + 10)
        blocks = [peb(0, 0, 1, fs[:LEB]), b'garbage' * 100 + b'\0' * (PEB - 700), peb(0, 1, 2, fs[LEB:])]
        code, out, err = self.run_sim(blocks, bad=1)
        self.assertEqual((code, out), (0, fs), err)
        code, _, err = self.run_sim(blocks[:1] + [b'\xff' * PEB] * 2)
        self.assertEqual(code, 1)
        self.assertIn('missing block', err)

    def test_not_ubi_or_not_squashfs_refused(self):
        code, _, err = self.run_sim([b'\0' * PEB])
        self.assertEqual(code, 1)
        self.assertIn('not UBI', err)
        code, _, err = self.run_sim([peb(0, 0, 1, b'not a squashfs')])
        self.assertEqual(code, 1)
        self.assertIn('no SquashFS', err)


if __name__ == '__main__':
    unittest.main()
