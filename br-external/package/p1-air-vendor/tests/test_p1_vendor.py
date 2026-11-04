import importlib.util
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[2]
spec = importlib.util.spec_from_file_location("p1_vendor", PACKAGE / "extract.py")
vendor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vendor)
fetch_spec = importlib.util.spec_from_file_location("p1_fetch", PACKAGE / "fetch.py")
fetcher = importlib.util.module_from_spec(fetch_spec)
fetch_spec.loader.exec_module(fetcher)


class VendorTests(unittest.TestCase):
    def test_bad_cached_image_is_not_used_or_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            cached = Path(directory) / "stock.img"
            cached.write_bytes(b"corrupted cache")
            with patch.object(fetcher.subprocess, "run") as download:
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    fetcher.fetch(cached)
                download.assert_not_called()
            self.assertEqual(cached.read_bytes(), b"corrupted cache")

    def test_bad_download_is_never_published(self):
        with tempfile.TemporaryDirectory() as directory:
            cached = Path(directory) / "stock.img"

            def wrong_response(command, **kwargs):
                Path(command[command.index("-O") + 1]).write_bytes(b"HTML instead of firmware")

            with patch.object(fetcher.subprocess, "run", side_effect=wrong_response):
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    fetcher.fetch(cached)
            self.assertEqual(list(cached.parent.iterdir()), [])

    def test_bad_image_rejected_before_decompression(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            image = base / "bad.img"
            image.write_bytes(b"OTRA" + bytes(1024))
            with patch.object(vendor.otra, "lzo_decoder") as decoder:
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    vendor.extract(image, base / "out", Path("missing"), Path("missing"))
                decoder.assert_not_called()
            self.assertFalse((base / "out").exists())

    def test_profile_rejects_wrong_radio_before_tool_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            radio = base / "radio.img"
            radio.write_bytes(bytes(100))
            result = subprocess.run([
                "python3", str(PACKAGE / "generate-radio-profile.py"),
                "--radio", str(radio), "--tool-prefix", "/does/not/exist/",
                "--output", str(base / "profile.c")], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"P1 radio hash mismatch", result.stderr)
            self.assertFalse((base / "profile.c").exists())

    def bundle(self, base, password=None):
        target, images = base / "target", base / "images"
        images.mkdir(exist_ok=True)
        air = target / "usrdata/fpv/air"
        air.mkdir(parents=True, exist_ok=True)
        (air / "root-login.sh").write_text("test placeholder\n")
        env = {**os.environ, "TARGET_DIR": str(target), "BINARIES_DIR": str(images)}
        env.pop("FPVOS_AIR_ROOT_PASSWORD", None)
        env.pop("FPVOS_AIR_SSH_KEYS", None)
        if password is not None:
            env["FPVOS_AIR_ROOT_PASSWORD"] = password
        subprocess.run(["sh", str(ROOT / "br-external/board/p1-air/post-image.sh")],
                       env=env, check=True)
        return images / "p1-air-app.tar.gz"

    def test_bundle_default_root_password_and_no_stock_files(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = self.bundle(Path(directory))
            with tarfile.open(archive) as tar:
                self.assertTrue(all(m.name == "air" or m.name.startswith("air/") for m in tar))
                entry = tar.getmember("air/ssh/root.hash")
                self.assertEqual(entry.mode, 0o600)
                hashed = tar.extractfile(entry).read().strip().decode()
            salt = hashed.split("$")[2]
            expected = subprocess.check_output(
                ["openssl", "passwd", "-6", "-salt", salt, "-stdin"], input=b"root\n")
            self.assertEqual(hashed, expected.decode().strip())

    def test_empty_password_removes_previous_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self.bundle(base)
            archive = self.bundle(base, "")
            with tarfile.open(archive) as tar:
                self.assertNotIn("air/ssh/root.hash", tar.getnames())


if __name__ == "__main__":
    unittest.main()
