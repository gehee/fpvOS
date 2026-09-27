#!/usr/bin/env python3
"""Populate vendor/ with the proprietary files fpvOS needs but cannot ship.

Every file comes from Caddx's own firmware - fpvOS never hosts or redistributes
it. Sources, easiest first:

  extract-vendor.py                       (the default: --download)
      Download the stock Caddx firmware from the official URL, cache it under
      ~/.cache/fpvos, and extract. No manual firmware hunting. Configure the
      link with FPVOS_FIRMWARE_URL (see the download center link below) or the
      FIRMWARE_URL constant. Needs `ubireader` (pip install ubi_reader).

  extract-vendor.py --from-ota Ascent_..._.img
      Extract from a firmware image you already downloaded. The image's rootfs
      is a UBI volume; needs `ubireader` on the PATH.

  extract-vendor.py --from-device root@192.168.3.1
      Pull from a VRX Pro you have shell access to (stock or fpvOS image).
      Uses ssh + tar; dropbear on the stock image has no sftp/scp server.

The wanted-file list lives in vendor/MANIFEST next to this script's output.
"""
import argparse
import hashlib
import struct
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"

# Stock Caddx/Ascent firmware to extract the vendor blobs from. This is Caddx's
# own firmware release - fpvOS never hosts or redistributes it; --download just
# automates fetching it so users don't hunt for it by hand. The release ships as
# a zip (the Caddx PC-Tool bundle); we pull the VRX Pro image out of it. Point
# FPVOS_FIRMWARE_URL at a newer release to update.
#
# The default is Caddx's own download-centre link, which is a share URL whose
# *contents* can change without the URL changing. So the build is only as
# reproducible as that file. Known-good, the release fpvOS is developed and
# tested against:
#
#   release zip   833dc686a71e8e834096bdd97d8fc1392eee550e04bd219d1d6e04dd435a7997
#   VRX Pro image 8e06ee54db882ac8d8c84a96f94bbaf87e245ddb0cc8e59dab460e10cd898389
#                 (Ascent_VRX_Pro_18_21_10.img)
#
# These are recorded, not enforced: pinning by default would break everyone the
# day Caddx publishes an update. Set FPVOS_FIRMWARE_SHA256 to the zip hash above
# to make a build refuse anything else - worth doing for a release runner, where
# silently extracting blobs from a different firmware is the bug you cannot see.
FIRMWARE_URL    = os.environ.get(
    "FPVOS_FIRMWARE_URL",
    "https://drive.google.com/file/d/1_IXl5OaJPVny78kg80CSn3FpWzYXQg3U/view")
FIRMWARE_SHA256 = os.environ.get("FPVOS_FIRMWARE_SHA256", "")   # optional integrity pin
# Which image inside the release zip carries the goggle rootfs (the vendor blobs).
FIRMWARE_IMG_GLOB = "Ascent_VRX_Pro_*.img"
CACHE_DIR = pathlib.Path(os.environ.get(
    "FPVOS_CACHE", pathlib.Path.home() / ".cache" / "fpvos"))

# vendor-relative destination -> path inside the stock rootfs
ROOTFS_WANT = {
    "rootfs/ar8030soc/daemon": "ar8030soc/daemon",
    "rootfs/ar8030soc/artosyn_drv.ko": "ar8030soc/artosyn_drv.ko",
    "rootfs/ar8030soc/libar8030_client.so": "ar8030soc/libar8030_client.so",
    # WiFi (RTL8188FU-family USB chip), used by usr/sbin/fpvos-wifi
    "rootfs/lib/modules/RTL8189FU.ko": "usr/lib/modules/RTL8189FU.ko",
    "rootfs/ar8030soc/cmd_dbg": "ar8030soc/cmd_dbg",
    "rootfs/ar8030soc/fpv_boardtype": "ar8030soc/fpv_boardtype",
    "rootfs/ar8030soc/fpv_cmd": "ar8030soc/fpv_cmd",
    "rootfs/ar8030soc/autoload": "ar8030soc/autoload",
    "rootfs/ar8030soc/conf.json": "ar8030soc/conf.json",
    "rootfs/ar8030soc/pwm_ctl.sh": "ar8030soc/pwm_ctl.sh",
    "rootfs/ar8030soc/app_monitor.sh": "ar8030soc/app_monitor.sh",
    "rootfs/ar8030soc/modules_install.sh": "ar8030soc/modules_install.sh",
    "rootfs/ar8030soc/inv-mpu6509.ko": "ar8030soc/inv-mpu6509.ko",
    "rootfs/ar8030soc/inv-mpu6509-spi.ko": "ar8030soc/inv-mpu6509-spi.ko",
    "rootfs/lib/firmware/bb_demo_cx485_2PA.img": "usr/lib/firmware/bb_demo_cx485_2PA.img",
    "rootfs/lib/firmware/bb_config_gnd_pro.json": "usr/lib/firmware/bb_config_gnd_pro.json",
    "rootfs/usr/lib/libmali.so.1": "usr/lib/libmali.so.1",
    "rootfs/usr/lib/libmali-hook.so.1": "usr/lib/libmali-hook.so.1",
    "rootfs/usr/lib/librga.so.2": "usr/lib/librga.so.2",
    "rootfs/usr/lib/librockchip_mpp.so.1": "usr/lib/librockchip_mpp.so.1",
    "rootfs/usr/lib/libar8030_client.so": "ar8030soc/libar8030_client.so",
}

# Only reachable from a live device, not from an OTA rootfs.
DEVICE_EXTRA = {
    "rootfs/factory/fact_env.json": "/factory/fact_env.json",
    "rootfs/factory/user_cfg.json": "/factory/user_cfg.json",
}

# The stock boot images, unmodified, for the fpvos-bootchain package
# (boot/mkbootchain.py) to turn into the SD card's boot chain. Partitions of
# the firmware's Rockchip update image, next to the rootfs.
STOCK_PARTS = {"uboot": "stock/uboot.img", "boot": "stock/boot.img"}


def stock_boot_images(data: bytes) -> dict[str, bool]:
    """Save the stock uboot.img and boot.img out of a Rockchip update image
    (RKFW wrapping RKAF). RKAF part entries are 0x70 bytes from 0x8c: name[32],
    file[60], part_size, pos (from the RKAF start), nand_addr, padded_size,
    size."""
    found = {dest: False for dest in STOCK_PARTS.values()}
    base = data.find(b"RKAF")
    if base < 0:
        return found
    n = struct.unpack_from("<I", data, base + 0x88)[0]
    for i in range(min(n, 32)):
        e = base + 0x8C + i * 0x70
        name = data[e:e + 32].split(b"\0")[0].decode(errors="replace")
        pos, size = struct.unpack_from("<I", data, e + 96)[0], struct.unpack_from("<I", data, e + 108)[0]
        dest = STOCK_PARTS.get(name)
        if dest and size:
            out = VENDOR / dest
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data[base + pos:base + pos + size])
            found[dest] = True
    return found


def place(dest_rel: str, src: pathlib.Path) -> bool:
    dest = VENDOR / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not src.is_file():
        return False
    shutil.copy2(src, dest)
    # ubireader does not preserve the executable bit, so everything comes out
    # of a firmware extraction mode 0644 - including the baseband daemon. The
    # image then boots with the radio hardware perfectly happy and
    # "nice: can't execute /ar8030soc/daemon: Permission denied" in the log,
    # after which kestrel waits 120s for a daemon that can never start. Mark
    # ELF binaries and shell scripts executable on the way in.
    with open(dest, "rb") as f:
        head = f.read(4)
    if head[:4] == b"\x7fELF" or head[:2] == b"#!":
        dest.chmod(0o755)
    return True


def note_pairing_list() -> None:
    """A firmware download carries the shared vendor code, never the pairing
    list: /factory/user_cfg.json, the MACs of the air units this goggle is
    paired with, is written per unit. The image does not need it - at every
    boot S50factory merges the list stock keeps on the goggle's own NAND - but
    say what to expect, since a goggle never paired under stock links only
    after an air unit is bound from the menu."""
    if (VENDOR / "rootfs/factory/user_cfg.json").is_file():
        return
    print("\n" + "=" * 72)
    print("  No pairing list in this extraction - a download never has one,")
    print("  and the image does not need it:")
    print()
    print("  - air units paired under stock are picked up at every boot, read")
    print("    from the goggle's own NAND")
    print("  - never paired under stock? Bind the air unit once from the menu")
    print("=" * 72 + "\n")


def report(found: dict[str, bool]) -> None:
    missing = [k for k, ok in found.items() if not ok]
    print(f"placed {sum(found.values())}/{len(found)} files under {VENDOR}")
    for m in missing:
        print(f"  MISSING: {m}")
    if missing:
        sys.exit(1)


def from_device(host: str) -> None:
    def pull(remote: str, dest_rel: str) -> bool:
        dest = VENDOR / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["ssh", host, f"cat {remote}"], capture_output=True)
        if r.returncode != 0 or not r.stdout:
            return False
        dest.write_bytes(r.stdout)
        return True

    found = {}
    for dest, rel in ROOTFS_WANT.items():
        # On a stock device these live under /; on an fpvOS device the
        # ar8030soc files are at the same absolute paths.
        found[dest] = pull("/" + rel, dest) or pull(
            "/" + dest.removeprefix("rootfs/"), dest)
    for dest, remote in DEVICE_EXTRA.items():
        found[dest] = pull(remote, dest)
    report(found)


def from_ota(img: pathlib.Path) -> None:
    if not shutil.which("ubireader_extract_files"):
        sys.exit("ubireader not found. Install it with:\n"
                 "  pip install ubi_reader   (or: pip install --break-system-packages ubi_reader)\n"
                 "It unpacks the UBIFS rootfs from the firmware.")
    data = img.read_bytes()
    # The OTA is RKFW -> RKAF -> (partitions). The rootfs partition is a UBI
    # image; find the first UBI erase-block magic and carve to the end - the
    # rootfs is the last large partition in every image we have seen.
    off = data.find(b"UBI#")
    if off < 0:
        sys.exit("no UBI magic found in image - not a supported OTA?")
    with tempfile.TemporaryDirectory() as td:
        ubi = pathlib.Path(td, "rootfs.ubi")
        ubi.write_bytes(data[off:])
        out = pathlib.Path(td, "out")
        r = subprocess.run(["ubireader_extract_files", "-k", "-o", str(out), str(ubi)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"ubireader failed: {r.stderr[-500:]}")
        # ubireader nests output per-volume; search for each wanted file.
        found = {}
        for dest, rel in ROOTFS_WANT.items():
            hits = list(out.rglob(rel))
            found[dest] = bool(hits) and place(dest, hits[0])
        found.update(stock_boot_images(data))
        note_pairing_list()
        report(found)


def _sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _drive_direct(url: str) -> str:
    """Rewrite a Google Drive share/view link to a direct-download URL that
    bypasses the large-file virus-scan interstitial. Non-Drive URLs pass
    through unchanged."""
    m = re.search(r"drive\.google\.com/(?:file/d/|.*[?&]id=)([\w-]+)", url)
    if not m:
        return url
    fid = m.group(1)
    return (f"https://drive.usercontent.google.com/download"
            f"?id={fid}&export=download&confirm=t")


def _http_download(url: str, dest: pathlib.Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "fpvos-extract"})
    try:
        with urllib.request.urlopen(req) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length", 0))
            done = 0
            while (chunk := r.read(1 << 20)):
                f.write(chunk); done += len(chunk)
                if total:
                    print(f"\r  {done*100//total}%  ({done>>20}/{total>>20} MB)",
                          end="", flush=True)
        print()
    except Exception as e:
        tmp.unlink(missing_ok=True)
        sys.exit(f"download failed: {e}")
    # Guard against Drive quota / login pages served as HTML instead of the file.
    with open(tmp, "rb") as f:
        head = f.read(4)
    if head[:2] not in (b"PK", b"RK") and head not in (b"UBI#",):
        tmp.unlink(missing_ok=True)
        sys.exit("download did not return firmware (Google Drive quota, or the "
                 "link changed). Try again later, or use --from-device.")
    tmp.rename(dest)


def ensure_firmware() -> pathlib.Path:
    """Return the goggle rootfs image, downloading+caching the stock Caddx
    release on first use so the user never fetches firmware by hand. The release
    is a zip; the VRX Pro image is extracted from it into the cache."""
    if not FIRMWARE_URL:
        sys.exit("No firmware URL configured. Set FPVOS_FIRMWARE_URL, or use "
                 "--from-ota <file> / --from-device root@<ip>.")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    url = _drive_direct(FIRMWARE_URL)
    dl = CACHE_DIR / "caddx_release.bin"      # zip or raw image
    if not (dl.is_file() and (not FIRMWARE_SHA256 or _sha256(dl) == FIRMWARE_SHA256)):
        print(f"downloading stock Caddx firmware:\n  {FIRMWARE_URL}\n  -> {dl}")
        _http_download(url, dl)
        if FIRMWARE_SHA256 and _sha256(dl) != FIRMWARE_SHA256:
            dl.unlink(missing_ok=True)
            sys.exit(f"checksum mismatch (expected {FIRMWARE_SHA256})")
        print(f"cached: {dl}")
    else:
        print(f"using cached download: {dl}")

    if not zipfile.is_zipfile(dl):
        return dl                              # already a raw image
    with zipfile.ZipFile(dl) as z:
        import fnmatch
        member = next((n for n in z.namelist()
                       if fnmatch.fnmatch(pathlib.PurePosixPath(n).name, FIRMWARE_IMG_GLOB)), None)
        if not member:
            sys.exit(f"no {FIRMWARE_IMG_GLOB} inside the release zip")
        img = CACHE_DIR / pathlib.PurePosixPath(member).name
        if not img.is_file():
            print(f"extracting {pathlib.PurePosixPath(member).name} from the release zip")
            with z.open(member) as src, open(img, "wb") as f:
                shutil.copyfileobj(src, f, 1 << 20)
        return img


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--download", action="store_true",
                   help="download stock Caddx firmware (cached) and extract - the default")
    g.add_argument("--from-device", metavar="USER@HOST")
    g.add_argument("--from-ota", metavar="OTA.img", type=pathlib.Path)
    a = ap.parse_args()
    if a.from_device:
        from_device(a.from_device)
    elif a.from_ota:
        from_ota(a.from_ota)
    else:                        # default: download + cache + extract
        from_ota(ensure_firmware())


if __name__ == "__main__":
    main()
