#!/usr/bin/env python3
"""Extract the codec firmware (chagall.bin) from the Caddx Ascent VRX firmware.

Read a pinned NAND OTRA image; extract one file from its UBI/SquashFS root.

This handles factory-generated dynamic UBI volumes, not live NAND dumps or
UBIFS. Input and output SHA-256 checks are performed by the Buildroot recipe.
No vendor code runs and no filesystem contents are extracted onto the host.
"""

import argparse
import ctypes
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib


MAX_PARTITION = 128 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def partition(image, name, decompress):
    base = 128 if image.startswith(b"ASW\0") else 0
    require(len(image) >= base + 544, "truncated OTRA header")
    require(image[base:base + 8] == b"OTRA\x01\x01\x02\x02",
            "unsupported OTRA format")
    extra, digest_size, signature_size = struct.unpack_from(
        "<HHH", image, base + 8)
    require((digest_size, signature_size) == (32, 256),
            "unsupported OTRA authentication fields")
    size, root, ddr, parts, chunks = struct.unpack_from(
        "<QIIHH", image, base + 16)
    body = base + 544
    require(size == len(image) - body, "OTRA body length mismatch")
    require(hashlib.sha256(image[body:]).digest() ==
            image[base + 256:base + 288],
            "OTRA body digest mismatch")
    table = body + extra + root + ddr
    end = table + parts * 52 + chunks * 32
    require(0 < parts <= 128 and 0 < chunks <= 4096 and end <= len(image),
            "invalid OTRA tables")
    matches = []
    for index in range(parts):
        raw_name, start, length, flags = struct.unpack_from(
            "<32sQQI", image, table + index * 52)
        if raw_name.split(b"\0", 1)[0] == name.encode("ascii"):
            matches.append((start, length, flags))
    require(len(matches) == 1, "missing or duplicate OTRA partition")
    start, length, flags = matches[0]
    require(flags == 1 and 0 < length <= MAX_PARTITION,
            "invalid OTRA partition")
    result = bytearray(b"\xff") * length
    ranges = []
    for index in range(chunks):
        offset, address, packed, raw = struct.unpack_from(
            "<QQQQ", image, table + parts * 52 + index * 32)
        require(packed > 0 and raw > 0 and base + offset >= end
                and base + offset + packed <= len(image),
                "invalid OTRA chunk bounds")
        if address + raw <= start or address >= start + length:
            continue
        begin, finish = address - start, address - start + raw
        require(0 <= begin < finish <= length,
                "chunk crosses partition boundary")
        require(all(finish <= a or begin >= b for a, b in ranges),
                "overlapping OTRA chunks")
        decoded = decompress(image[base + offset:base + offset + packed], raw)
        require(len(decoded) == raw, "LZO output size mismatch")
        result[begin:finish] = decoded
        ranges.append((begin, finish))
    require(ranges, "partition has no data")
    return bytes(result)


def lzo_decoder(library):
    function = ctypes.CDLL(str(library)).lzo1x_decompress_safe
    function.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                         ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p]
    function.restype = ctypes.c_int

    def decompress(source, size):
        require(0 < size <= MAX_PARTITION, "invalid LZO output size")
        output = ctypes.create_string_buffer(size)
        actual = ctypes.c_size_t(size)
        result = function(source, len(source), output,
                          ctypes.byref(actual), None)
        require(result == 0 and actual.value == size,
                "LZO decompression failed")
        return output.raw

    return decompress


def header_crc(header):
    return (zlib.crc32(header[:60]) ^ 0xffffffff) == struct.unpack_from(
        ">I", header, 60)[0]


def volume(image, peb_size, volume_id):
    require(4096 <= peb_size <= 1024 * 1024 and len(image) % peb_size == 0,
            "invalid UBI eraseblock size")
    blocks = {}
    geometry = set()
    for offset in range(0, len(image), peb_size):
        block = image[offset:offset + peb_size]
        if block == b"\xff" * peb_size:
            continue
        ec = block[:64]
        require(ec[:5] == b"UBI#\x01" and header_crc(ec),
                "invalid UBI erase counter header")
        vid_offset, data_offset = struct.unpack_from(">II", ec, 16)
        require(64 <= vid_offset and vid_offset + 64 <= data_offset < peb_size,
                "invalid UBI offsets")
        vid = block[vid_offset:vid_offset + 64]
        if vid == b"\xff" * 64:
            continue
        require(vid[:5] == b"UBI!\x01" and header_crc(vid),
                "invalid UBI volume header")
        vid_id, number = struct.unpack_from(">II", vid, 8)
        if vid_id != volume_id:
            continue
        require(vid[5:8] == b"\x01\0\0",
                "only factory dynamic UBI volumes are supported")
        require(vid[20:36] == bytes(16), "unsupported UBI data size/padding")
        require(number not in blocks, "duplicate UBI logical block")
        blocks[number] = block[data_offset:]
        geometry.add((vid_offset, data_offset,
                      struct.unpack_from(">I", ec, 24)[0]))
    require(blocks and sorted(blocks) == list(range(len(blocks)))
            and len(geometry) == 1,
            "missing UBI blocks or mixed geometry")
    result = b"".join(blocks[n] for n in range(len(blocks)))
    require(result.startswith(b"hsqs"), "selected UBI volume is not SquashFS")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--partition", required=True)
    parser.add_argument("--peb-size", type=int, required=True)
    parser.add_argument("--volume-id", type=int, required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--liblzo", type=Path, required=True)
    parser.add_argument("--unsquashfs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image = partition(args.image.read_bytes(), args.partition,
                      lzo_decoder(args.liblzo))
    filesystem = volume(image, args.peb_size, args.volume_id)
    with tempfile.TemporaryDirectory(dir=args.output.parent) as temporary:
        root = Path(temporary) / "root.squashfs"
        root.write_bytes(filesystem)
        blob = subprocess.run(
            [str(args.unsquashfs), "-cat", str(root), args.member],
            check=True, stdout=subprocess.PIPE).stdout
        require(blob, "empty extracted file")
        staged = Path(temporary) / "blob"
        staged.write_bytes(blob)
        staged.replace(args.output)


if __name__ == "__main__":
    main()
