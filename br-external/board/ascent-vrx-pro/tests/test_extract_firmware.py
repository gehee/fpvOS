#!/usr/bin/env python3
"""scripts/extract-ascent-vrx-pro-firmware.py: the cached download belongs to
one URL, a download shorter than its Content-Length is refused, and an image
extracted from the release zip is reused only when it matches the member."""
from pathlib import Path
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / 'scripts/extract-ascent-vrx-pro-firmware.py'


def load():
    spec = importlib.util.spec_from_file_location('extract_vrx_pro', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Response(io.BytesIO):
    def __init__(self, body, length=None):
        super().__init__(body)
        self.headers = {} if length is False else {'Content-Length': str(len(body) if length is None else length)}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Base(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.d = Path(temp.name)
        self.x = load()
        self.x.CACHE_DIR = self.d / 'cache'
        self.x.FIRMWARE_SHA256 = ''
        self.served = {}
        self.fetched = []

    def urlopen(self, req):
        self.fetched.append(req.full_url)
        body, length = self.served[req.full_url]
        return Response(body, length)

    def serve(self, url, body, length=None):
        self.served[url] = (body, length)

    def download(self, url):
        self.x.FIRMWARE_URL = url
        with mock.patch.object(self.x.urllib.request, 'urlopen', self.urlopen), \
             mock.patch('sys.stdout', io.StringIO()):
            return self.x.release_download()


class Download(Base):
    def test_the_same_url_reuses_the_cache(self):
        self.serve('https://a/r.zip', b'PK release A')
        self.download('https://a/r.zip')
        self.assertEqual(self.download('https://a/r.zip').read_bytes(), b'PK release A')
        self.assertEqual(len(self.fetched), 1)

    def test_another_url_downloads_that_release(self):
        self.serve('https://a/r.zip', b'PK release A')
        self.serve('https://b/r.zip', b'PK release B')
        self.download('https://a/r.zip')
        self.assertEqual(self.download('https://b/r.zip').read_bytes(), b'PK release B')
        self.assertEqual(self.fetched, ['https://a/r.zip', 'https://b/r.zip'])

    def test_a_cache_with_no_record_of_its_url_is_downloaded_again(self):
        self.x.CACHE_DIR.mkdir()
        (self.x.CACHE_DIR / 'caddx_release.bin').write_bytes(b'PK from an older script')
        self.serve('https://a/r.zip', b'PK release A')
        self.assertEqual(self.download('https://a/r.zip').read_bytes(), b'PK release A')

    def test_a_pinned_hash_decides_on_its_own(self):
        import hashlib
        self.x.CACHE_DIR.mkdir()
        (self.x.CACHE_DIR / 'caddx_release.bin').write_bytes(b'PK pinned')
        self.x.FIRMWARE_SHA256 = hashlib.sha256(b'PK pinned').hexdigest()
        self.assertEqual(self.download('https://a/r.zip').read_bytes(), b'PK pinned')
        self.assertEqual(self.fetched, [])

    def test_a_short_download_is_refused(self):
        self.serve('https://a/r.zip', b'PK half', length=1000)
        with self.assertRaises(SystemExit) as e:
            self.download('https://a/r.zip')
        self.assertIn('incomplete', str(e.exception))
        self.assertEqual(sorted(p.name for p in self.x.CACHE_DIR.iterdir()), [])

    def test_no_content_length_is_accepted(self):
        self.serve('https://a/r.zip', b'PK chunked', length=False)
        self.assertEqual(self.download('https://a/r.zip').read_bytes(), b'PK chunked')

    def test_a_failed_short_download_keeps_the_old_cache_out(self):
        self.serve('https://a/r.zip', b'PK release A')
        self.download('https://a/r.zip')
        self.serve('https://b/r.zip', b'PK half', length=1000)
        with self.assertRaises(SystemExit):
            self.download('https://b/r.zip')
        # The old release is not passed off as B's, then or later.
        self.serve('https://b/r.zip', b'PK release B')
        self.assertEqual(self.download('https://b/r.zip').read_bytes(), b'PK release B')


class Member(Base):
    NAME = 'Ascent_VRX_Pro_18_21_10.img'
    DATA = os.urandom(3 << 20)

    def setUp(self):
        super().setUp()
        self.x.CACHE_DIR.mkdir()
        self.zip = self.d / 'release.zip'
        with zipfile.ZipFile(self.zip, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(f'PC-Tool/{self.NAME}', self.DATA)
        self.img = self.x.CACHE_DIR / self.NAME

    def member(self):
        with mock.patch('sys.stdout', io.StringIO()) as out:
            got = self.x.release_member(self.zip, self.x.FIRMWARE_IMG_GLOB)
        self.extracted = 'extracting' in out.getvalue()
        return got

    def test_extracts_once_then_reuses(self):
        self.assertEqual(self.member().read_bytes(), self.DATA)
        self.assertTrue(self.extracted)
        self.assertEqual(self.member(), self.img)
        self.assertFalse(self.extracted)

    def test_a_truncated_image_is_extracted_again(self):
        self.img.write_bytes(self.DATA[:1 << 20])
        self.assertEqual(self.member().read_bytes(), self.DATA)
        self.assertTrue(self.extracted)

    def test_an_image_of_the_right_size_but_other_content_is_extracted_again(self):
        self.img.write_bytes(bytes(len(self.DATA)))
        self.assertEqual(self.member().read_bytes(), self.DATA)

    def test_an_interrupted_extraction_leaves_nothing(self):
        def interrupted(src, dst, length=0):
            dst.write(src.read(1 << 20))
            raise KeyboardInterrupt
        with mock.patch.object(self.x.shutil, 'copyfileobj', interrupted), self.assertRaises(KeyboardInterrupt):
            self.member()
        self.assertEqual(list(self.x.CACHE_DIR.iterdir()), [])
        self.assertEqual(self.member().read_bytes(), self.DATA)

    def test_no_member(self):
        with mock.patch('sys.stdout', io.StringIO()):
            self.assertIsNone(self.x.release_member(self.zip, 'nothing_*.img'))


class Cli(unittest.TestCase):
    def test_help(self):
        r = subprocess.run([sys.executable, str(SCRIPT), '--help'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        for flag in ('--download', '--from-ota', '--from-device'):
            self.assertIn(flag, r.stdout)


if __name__ == '__main__':
    unittest.main()
