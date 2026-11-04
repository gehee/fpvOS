#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Append the P1 entry guard in the Image's zero-init space, before LZ4 packing."""
import argparse
from pathlib import Path
import struct


def branch(offset):
    if offset % 4 or not -(1 << 27) <= offset < (1 << 27):
        raise ValueError('guard branch out of range')
    return struct.pack('<I', 0x14000000 | ((offset // 4) & 0x3ffffff))


def guard(image, code):
    if len(image) < 64 or image[56:60] != b'ARM\x64' or len(image) % 4:
        raise ValueError('expected aligned ARM64 Image')
    if struct.unpack_from('<Q', image, 8)[0] or struct.unpack_from('<I', image, 4)[0] >> 26 != 5:
        raise ValueError('unexpected ARM64 entry layout')
    if len(code) != 60 or code[-4:] != branch(0):
        raise ValueError('unexpected boot guard layout')
    if len(image) + len(code) > struct.unpack_from('<Q', image, 16)[0]:
        raise ValueError('guard exceeds Image allocation')
    return branch(len(image)) + image[4:] + code[:-4] + branch(4 - len(image) - len(code) + 4)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('image', type=Path)
    p.add_argument('guard', type=Path)
    p.add_argument('output', type=Path)
    a = p.parse_args()
    a.output.write_bytes(guard(a.image.read_bytes(), a.guard.read_bytes()))
