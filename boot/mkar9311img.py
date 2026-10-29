#!/usr/bin/env python3
"""Wrap an ARM64 Linux LZ4 uImage for the AR9311 vendor RAM boot command.

This is an unsigned OTRA boot container, not a flash upgrade package.
"""
import argparse
from pathlib import Path
import struct
import zlib


def wrap(image):
    if len(image) < 64:
        raise ValueError("truncated uImage header")
    magic, hcrc, _, size, load, entry, dcrc, os_, arch, kind, comp = struct.unpack(
        ">7I4B", image[:32]
    )
    if magic != 0x27051956 or (os_, arch, kind, comp) != (5, 22, 2, 5):
        raise ValueError("expected an ARM64 Linux LZ4 kernel uImage")
    # Accept the stock kernel address and the aligned mainline address.
    if load != entry or load not in (0x200A0000, 0x20200000):
        raise ValueError("unexpected kernel load or entry address")
    header = bytearray(image[:64])
    header[4:8] = bytes(4)
    if zlib.crc32(header) != hcrc:
        raise ValueError("uImage header CRC mismatch")
    if len(image) != size + 64 or zlib.crc32(image[64:]) != dcrc:
        raise ValueError("uImage payload size or CRC mismatch")
    payload = image + bytes(-(64 + len(image)) % 256)
    header = bytearray(64)
    header[:4] = b"OTRA"
    struct.pack_into("<II", header, 12, load, len(payload))
    struct.pack_into("<I", header, 32, sum(payload) & 0xFFFFFFFF)
    if len(header) + len(payload) > 0x800000:
        raise ValueError("container exceeds the 8 MiB RAM staging window")
    return bytes(header) + payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        data = wrap(args.input.read_bytes())
    except ValueError as error:
        parser.error(str(error))
    args.output.write_bytes(data)


if __name__ == "__main__":
    main()
