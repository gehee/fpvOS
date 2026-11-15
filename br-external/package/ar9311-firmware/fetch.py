#!/usr/bin/env python3
"""Cache a hash-pinned firmware download, including URLs with query parameters."""
import argparse
import hashlib
from pathlib import Path
import shlex
import subprocess
import tempfile


def verify(path, digest):
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != digest:
            raise ValueError("firmware SHA-256 mismatch")


def fetch(destination, url, digest, wget="wget", max_bytes=32 * 1024 * 1024):
    if destination.exists():
        verify(destination, digest)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        staged = Path(directory) / "firmware.img"
        # Use Buildroot's configured host downloader and system CA store.
        # The separately built host Python does not carry the host CA bundle.
        subprocess.run([*shlex.split(wget), "-O", str(staged), url],
                       check=True, timeout=180)
        if staged.stat().st_size > max_bytes:
            raise ValueError("unexpected firmware download size")
        verify(staged, digest)
        staged.replace(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--wget", default="wget")
    parser.add_argument("--url", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--max-bytes", type=int, default=32 * 1024 * 1024)
    args = parser.parse_args()
    fetch(args.destination, args.url, args.sha256, args.wget, args.max_bytes)
