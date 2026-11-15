"""Compressed members and verified download caching, without vendor fixtures."""
import gzip
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


extract = load("codec_extract", "extract-ascent-vrx-firmware.py")
fetcher = load("codec_fetch", "fetch.py")


class MemberTests(unittest.TestCase):
    def test_plain_and_gzip_have_identical_output(self):
        blob = bytes(range(256)) * 8
        self.assertEqual(extract.decode_member(blob, False), blob)
        self.assertEqual(extract.decode_member(gzip.compress(blob), True), blob)

    def test_truncated_gzip_is_rejected(self):
        with self.assertRaises(EOFError):
            extract.decode_member(gzip.compress(b"firmware")[:-4], True)

    def test_bad_gzip_crc_is_rejected(self):
        blob = bytearray(gzip.compress(b"firmware"))
        blob[-8] ^= 1
        with self.assertRaises(gzip.BadGzipFile):
            extract.decode_member(bytes(blob), True)

    def test_gzip_expansion_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "size"):
            extract.decode_member(gzip.compress(bytes(16 * 1024 * 1024 + 1)), True)

    def test_empty_member_rejected(self):
        for blob, compressed in [(b"", False), (gzip.compress(b""), True)]:
            with self.assertRaisesRegex(ValueError, "size"):
                extract.decode_member(blob, compressed)


class FetchTests(unittest.TestCase):
    def test_verified_cache_does_not_download(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "firmware.img"
            target.write_bytes(b"verified")
            with patch.object(fetcher.subprocess, "run") as download:
                fetcher.fetch(target, "https://example.invalid/?id=pinned", hashlib.sha256(b"verified").hexdigest())
                download.assert_not_called()

    def test_download_published_only_after_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "firmware.img"
            url = "https://example.invalid/?id=pinned&confirm=t"
            def download(command, **kwargs):
                self.assertEqual(command[-1], url)
                Path(command[command.index("-O") + 1]).write_bytes(b"verified")
            with patch.object(fetcher.subprocess, "run", side_effect=download):
                fetcher.fetch(target, url, hashlib.sha256(b"verified").hexdigest())
            self.assertEqual(target.read_bytes(), b"verified")
            self.assertEqual(list(target.parent.iterdir()), [target])

    def test_oversized_download_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "firmware.img"
            def download(command, **kwargs):
                Path(command[command.index("-O") + 1]).write_bytes(b"oversize")
            with patch.object(fetcher.subprocess, "run", side_effect=download):
                with self.assertRaisesRegex(ValueError, "size"):
                    fetcher.fetch(target, "https://example.invalid/", hashlib.sha256(b"oversize").hexdigest(), max_bytes=4)
            self.assertEqual(list(target.parent.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
