#!/usr/bin/env python3
"""Extract a verified P1 stock rootfs without executing its contents."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

IMAGE_SHA256 = "4595ce951d79b7d6ddd31818d158928cd0bbbd982aa3e75245baa23aa821255c"
SOURCE = Path(__file__).resolve().parents[1] / "ar9311-firmware/extract-ascent-vrx-firmware.py"
spec = importlib.util.spec_from_file_location("otra", SOURCE)
otra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(otra)


def extract(image, output, library, unsquashfs):
    data = image.read_bytes()
    if hashlib.sha256(data).hexdigest() != IMAGE_SHA256:
        raise ValueError("P1 stock image SHA-256 mismatch; expected release 1.0.44")
    root = otra.volume(otra.partition(data, "userapp0", otra.lzo_decoder(library)),
                       131072, 0)
    output.mkdir(parents=True, exist_ok=True)
    # Verify the product before publishing any output. Do not unpack device
    # nodes or follow links from the vendor filesystem on the build host.
    with tempfile.TemporaryDirectory(dir=output) as directory:
        staged = Path(directory) / "root.squashfs"
        staged.write_bytes(root)
        version = subprocess.check_output([
            str(unsquashfs), "-cat", str(staged), "usr/usrdata/sdk_version.json"])
        info = json.loads(version)
        if info.get("product_version") != "P1_SKY" or info.get("software_version") != "1.0.44.rel":
            raise ValueError("unexpected P1 product/version")
        manifest = {"product": "P1_SKY", "version": "1.0.44.rel",
                    "image_sha256": IMAGE_SHA256,
                    "rootfs_sha256": hashlib.sha256(root).hexdigest(),
                    "partition": "userapp0", "peb_size": 131072,
                    "volume_id": 0, "kernel": "vendor 4.9.38 (unchanged)"}
        staged.replace(output / "root.squashfs")
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--liblzo", type=Path, required=True)
    parser.add_argument("--unsquashfs", type=Path, required=True)
    args = parser.parse_args()
    extract(args.image, args.output, args.liblzo, args.unsquashfs)


if __name__ == "__main__":
    main()
