"""Format rejection tests using synthetic data; no vendor firmware fixtures."""

import hashlib
import importlib.util
from pathlib import Path
import struct
import unittest
import zlib


spec = importlib.util.spec_from_file_location(
    "extract", Path(__file__).parents[1] / "extract.py")
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


def seal_otra(image):
    image[256:288] = hashlib.sha256(image[544:]).digest()
    return bytes(image)


def otra():
    image = bytearray(544 + 52 + 32 + 4)
    image[:8] = b"OTRA\x01\x01\x02\x02"
    struct.pack_into("<HHH", image, 8, 0, 32, 256)
    struct.pack_into("<QIIHH", image, 16, len(image) - 544, 0, 0, 1, 1)
    struct.pack_into("<32sQQI", image, 544, b"root", 4096, 4096, 1)
    struct.pack_into("<QQQQ", image, 596, 628, 4096, 4, 4)
    image[628:] = b"data"
    return bytearray(seal_otra(image))


def crc(header):
    struct.pack_into(">I", header, 60, zlib.crc32(header[:60]) ^ 0xffffffff)
    return header


def ubi(number=0, volume_id=0, kind=1):
    block = bytearray(b"\xff" * 4096)
    ec = bytearray(64)
    ec[:5] = b"UBI#\x01"
    struct.pack_into(">II", ec, 16, 64, 128)
    block[:64] = crc(ec)
    vid = bytearray(64)
    vid[:5] = b"UBI!\x01"
    vid[5] = kind
    struct.pack_into(">II", vid, 8, volume_id, number)
    block[64:128] = crc(vid)
    block[128:132] = b"hsqs"
    return block


class ExtractionTests(unittest.TestCase):
    def read_partition(self, image, name="root"):
        return extract.partition(image, name, lambda source, size: source)

    def test_partition_and_asw_prefix(self):
        for prefix in [b"", b"ASW\0" + bytes(124)]:
            result = self.read_partition(prefix + otra())
            self.assertEqual(result, b"data" + b"\xff" * 4092)

    def test_truncated_and_wrong_format(self):
        for image in [b"OTRA", bytes(1024), otra()[:-1]]:
            with self.subTest(size=len(image)), self.assertRaises(ValueError):
                self.read_partition(image)

    def test_body_digest(self):
        image = otra()
        image[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "digest"):
            self.read_partition(image)

    def test_missing_partition(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            self.read_partition(otra(), "absent")

    def test_partition_and_chunk_bounds(self):
        for offset, value in [(584, extract.MAX_PARTITION + 1), (596, 0),
                              (604, 8190), (612, 9999), (620, 9999)]:
            image = otra()
            struct.pack_into("<Q", image, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.read_partition(seal_otra(image))

    def test_decoder_output_length(self):
        with self.assertRaisesRegex(ValueError, "output size"):
            extract.partition(otra(), "root", lambda source, size: b"")

    def test_ubi_sorts_blocks_and_skips_other_volumes(self):
        image = ubi(1) + ubi(0, 7) + ubi(0) + b"\xff" * 4096
        self.assertEqual(extract.volume(image, 4096, 0),
                         bytes(ubi()[128:]) * 2)

    def test_ubi_corruption(self):
        for offset in [0, 16, 60, 64, 72, 124]:
            image = ubi()
            image[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                extract.volume(image, 4096, 0)

    def test_ubi_missing_duplicate_and_unsupported(self):
        for image in [ubi(1), ubi() + ubi(), ubi(volume_id=1), ubi(kind=2),
                      ubi()[:-1], b"\xff" * 4096]:
            with self.subTest(size=len(image)), self.assertRaises(ValueError):
                extract.volume(image, 4096, 0)

    def test_not_squashfs(self):
        image = ubi()
        image[128:132] = b"nope"
        with self.assertRaisesRegex(ValueError, "SquashFS"):
            extract.volume(image, 4096, 0)


if __name__ == "__main__":
    unittest.main()
