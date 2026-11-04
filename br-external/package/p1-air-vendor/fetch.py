#!/usr/bin/env python3
"""Cache the pinned official P1 release, including Drive's confirmation query."""
import argparse
import hashlib
from pathlib import Path
import shlex
import subprocess
import tempfile


URL = ("https://drive.usercontent.google.com/download?"
       "id=1xFnvQBfdlsUSR0zZc9IH_TJEP-gQCOJG&export=download&confirm=t")
DIGEST = "4595ce951d79b7d6ddd31818d158928cd0bbbd982aa3e75245baa23aa821255c"


def verify(path):
    with path.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != DIGEST:
            raise ValueError("P1 firmware SHA-256 mismatch")


def fetch(destination, wget="wget"):
    if destination.exists():
        verify(destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as directory:
        staged = Path(directory) / "firmware.img"
        # Use Buildroot's configured host downloader and system CA store.
        # The separately built host Python does not carry the host CA bundle.
        subprocess.run([*shlex.split(wget), "-O", str(staged), URL],
                       check=True, timeout=180)
        if staged.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("unexpected P1 firmware download size")
        verify(staged)
        staged.replace(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--wget", default="wget")
    args = parser.parse_args()
    fetch(args.destination, args.wget)
