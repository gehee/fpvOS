#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Create an unsigned fpvOS update bundle; no device access or flashing."""
import argparse
import hashlib
import os
import tempfile
from pathlib import Path
import struct
import zlib

from boards import get_profile


def build(images, board, release='development', vendor_restore=False):
    kind = int(vendor_restore)
    count = board['counts'][kind]
    if not count:
        raise ValueError('this board does not support this package kind')
    label = release.encode('ascii')
    if not label or len(label) >= 64 or any(c < 32 or c > 126 for c in label):
        raise ValueError('release must be 1..63 printable ASCII bytes')
    header = bytearray(512)
    header[:8] = b'FPVOSUP1'
    data = []
    for index, (name, limit) in enumerate(zip(board['names'][:count], board['limits'])):
        if vendor_restore:
            payload = (images / board['restore_sources'][index]).read_bytes()
            if len(payload) != limit:
                raise ValueError('restoration requires full-partition backups')
        else:
            payload = (images / name).read_bytes()
        if not 0 < len(payload) <= limit:
            raise ValueError(f'{name} exceeds its allowed size')
        offset = 96 + 104 * index
        struct.pack_into('<32sI64sI', header, offset, name.encode(), len(payload),
                         hashlib.sha256(payload).hexdigest().encode(), 0)
        data.append(payload)
    if 512 + sum(map(len, data)) > board['bundle_limits'][kind]:
        raise ValueError('bundle exceeds board storage capacity')
    struct.pack_into('<IIII64s', header, 8, 1, board['board_id'],
                     512 + sum(map(len, data)), len(data), label)
    struct.pack_into('<I', header, 88, int(vendor_restore))
    struct.pack_into('<I', header, 508, zlib.crc32(header))
    return bytes(header) + b''.join(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', required=True, help='board backend, e.g. ar9311')
    parser.add_argument('images', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--release', default='development', help='informational; no ordering policy')
    parser.add_argument('--replace', action='store_true', help='atomically replace an existing output')
    parser.add_argument('--vendor-restore', action='store_true', help='package original kernel/DTB backups; preserve the active vendor rootfs')
    args = parser.parse_args()
    payload = build(args.images, get_profile(args.board), args.release, args.vendor_restore)
    if args.replace:
        with tempfile.NamedTemporaryFile(dir=args.output.parent, delete=False) as output:
            temporary = Path(output.name)
            try:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
                os.replace(temporary, args.output)
            finally:
                temporary.unlink(missing_ok=True)
    else:
        with args.output.open('xb') as output:
            output.write(payload)
    print(f'{len(payload)} bytes; SHA256 {hashlib.sha256(payload).hexdigest()}')


if __name__ == '__main__':
    main()
