# Building fpvOS

fpvOS builds a complete SD-card image for the goggle from source, with one
manual step: extracting the proprietary vendor blobs from firmware you own.
Nothing proprietary ships in this repo.

## Dependencies

A Linux host. On Debian / Ubuntu, everything except the one Python package:

```sh
sudo apt install -y build-essential git wget cpio unzip rsync bc file \
    libncurses-dev libssl-dev python3 python3-pip mtools gdisk fdisk xz-utils
pip install ubi_reader          # or: pip install --break-system-packages ubi_reader
```

What each group is for:

- **build-essential, git, wget, cpio, unzip, rsync, bc, file, libncurses-dev,
  libssl-dev** — Buildroot's host prerequisites. Buildroot builds its own
  cross-toolchain, so you do **not** need a cross-gcc.
- **mtools, gdisk, fdisk** — SD-image assembly (`mformat`/`mcopy`/`mmd`,
  `sgdisk`, `sfdisk`; `sfdisk` left util-linux for its own `fdisk` package in
  Debian 11 / Ubuntu 22.04). The image is built **rootless** — no loop mounts, no
  sudo. (sudo is only needed to `dd` the finished image onto a card.)
- **xz-utils** — compresses the image to `sdcard.img.xz` for balenaEtcher.
- **python3 + `ubi_reader`** — vendor-blob extraction. `ubi_reader` unpacks the
  UBIFS rootfs out of the Caddx firmware. If it gives you trouble, `ubidump`
  is a lighter single-file UBIFS reader; the kernel route (`nandsim` +
  `ubiattach` + `mount -t ubifs`) also works but needs root and kernel modules.
  Only `--from-device` uses `ssh` instead of `ubi_reader`.

Also: **~20 GB free disk** and a coffee's worth of time for the first Buildroot
build (the cross-toolchain and all packages compile from source once).

## 1. Get the source

Buildroot is a submodule pinned to the version in `br-external/BUILDROOT_VERSION`,
so a recursive clone brings it down automatically:

```sh
git clone --recurse-submodules https://github.com/gehee/fpvOS && cd fpvOS
```

Already cloned without `--recurse-submodules`? Fetch it after the fact:

```sh
git submodule update --init --depth 1
```

## 2. Extract the vendor blobs

fpvOS needs the AR8030 baseband stack, the Mali GPU driver, and the Rockchip
media libraries. These are Caddx's own firmware — fpvOS never hosts them. By
default the script downloads the stock Caddx firmware from the official source,
caches it under `~/.cache/fpvos`, and extracts:

```sh
# Default: download stock Caddx firmware (cached) and extract
scripts/extract-vendor.py

# ...or the runtime files from a goggle you can SSH into (stock or fpvOS);
# the boot images still come from a firmware image, so run one of the others
# once as well:
scripts/extract-vendor.py --from-device root@192.168.3.1

# ...or from a firmware image you already downloaded:
scripts/extract-vendor.py --from-ota Ascent_..._.img
```

The download URL is set by `FPVOS_FIRMWARE_URL` (or the `FIRMWARE_URL` constant
in the script); it needs `ubireader` (`pip install ubi_reader`) to unpack.

The blobs land in `vendor/` (git-ignored). Re-run any time; the script reports
exactly what it found and what's missing. See [`vendor/MANIFEST`](../vendor/MANIFEST)
for the full list and where each file comes from.

### `/factory` — which air units your goggle is paired with

Everything above is code shared by every VRX Pro. The pairing list is not:
`/factory/user_cfg.json` holds the MAC addresses of the air units this goggle
is paired with (`bb_mac_addr_N`, a ring of up to 100). kestrel pushes them to
the baseband at startup, and its bind menu adds to them. The goggle's own
AR8030 MAC is not in there - the chip supplies it - which is why an air unit
bound under stock links to fpvOS without being bound again.

No firmware download contains the list, because it is written per unit. It
does not have to come from the build either. Stock keeps its copy on the
goggle's internal NAND, and at every boot `S50factory` reads it and adds any
air unit the card's list is missing:

- the NAND is only read: the partition is attached for the copy and detached
  again, the volume is mounted read-only, and nothing is written back
- an air unit bound in fpvOS is saved on the card, so stock does not see it
- a goggle never paired under stock starts with an empty list: bind the air
  unit once from the menu

`--from-device` still copies the list into `vendor/rootfs/factory/`, and the
build then bakes it into the image. That is only useful for a build meant for
that one goggle. The file is personal: do not put it in a public repo or hand
someone an image built with yours, and never ship it in a release.
`post-build.sh` says so whenever a build carries one.

The vendor's own `factory_mount.sh` is deliberately not used, and not shipped:
when a mount fails it reformats the volume, which would destroy the list it
exists to protect.

### The boot chain

The card boots through the stock U-Boot and kernel, adapted for the SD card at
build time: the `fpvos-bootchain` package runs
[`boot/mkbootchain.py`](../boot/mkbootchain.py) on the stock `uboot.img` and
`boot.img` that `extract-vendor.py` saves under `vendor/stock/` (from the
download or `--from-ota`). Everything it changes is in that script: three
U-Boot functions stubbed out so it can boot from SD, and a device tree whose
kernel command line mounts the card. It refuses a U-Boot build it does not
know, rather than patch it blind.

## 3. Build

```sh
./build.sh            # defconfig -> full Buildroot build -> SD image
```

Sub-commands for iterating:

```sh
./build.sh config     # (re)generate the Buildroot .config from the defconfig
./build.sh kestrel    # rebuild only kestrel into the sysroot
./build.sh image      # re-assemble the image (rootfs already built)
```

The result, in the repo root, is the image twice:

- `sdcard.img` — the raw image, for `dd`
- `sdcard.img.xz` — the same image compressed, for balenaEtcher or Raspberry
  Pi Imager, and the one to copy around

`COMPRESS=0 ./build.sh` skips the `.xz` when you're iterating and only `dd`.

## 4. Flash and boot

See [INSTALL.md](INSTALL.md) for flashing, first boot, and recovery back to
stock. The easy way is balenaEtcher with `sdcard.img.xz`; from a Linux shell:

```sh
sudo dd if=sdcard.img of=/dev/sdX bs=4M conv=fsync
# If the card is larger than the image, extend the backup GPT:
sudo sgdisk -e /dev/sdX
```

## How the image boots

The three-partition SD layout (a FAT fallback, the ext4 root, and a FIT boot
partition) and the loader/init sequence it needs are all handled by
`boot/mk-sd-image.sh`, using boot artifacts extracted from your own device.
You don't need to assemble any of it by hand — `./build.sh` does it.

## Troubleshooting

- **`vendor blobs missing`** — run `extract-vendor.py` (step 2); it prints what
  it couldn't find.
- **Buildroot fails on first package** — confirm you cloned the exact pinned
  version from `br-external/BUILDROOT_VERSION`.
- **Boots to a black screen** — almost always the loader; confirm
  `buildroot/output/images/uboot-patched.bin` exists (the fpvos-bootchain
  package makes it from `vendor/stock/uboot.img`).
