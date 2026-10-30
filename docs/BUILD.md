# Building fpvOS

fpvOS builds a complete SD-card image for the goggle, and an image for the
Ascent air units, from source, with one manual step: extracting the proprietary
vendor blobs from firmware you own. Nothing proprietary ships in this repo.

> **Just want to fly it?** You don't need to build anything: the images are on
> the [releases page](https://github.com/gehee/fpvOS/releases/latest), and
> [INSTALL.md](INSTALL.md) takes you from download to flying.

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

Also: **~30 GB free disk** and a long coffee's worth of time for the first
Buildroot build (the cross-toolchain, the kernel, Mesa and the LLVM it builds
with all compile from source once).

The applications and the radio's host stack are fetched from GitHub at the
commits this tree pins: kestrel, `ar-libre` and, for the air image,
`kestrel-air`. To build against a fork or a local checkout instead, set
`KESTREL_SITE`, `AR_LIBRE_SITE` or `KESTREL_AIR_SITE` to another git URL, or
`AR_LIBRE_OVERRIDE_SRCDIR=<path>` (and the matching `*_OVERRIDE_SRCDIR`) to a
checkout.

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

fpvOS needs the AR8030's firmware, Rockchip's `librga` and the stock boot
images. These are Caddx's own firmware — fpvOS never hosts them. By
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

### Open8030, the open radio firmware (optional)

Both images can carry [Open8030](https://github.com/gehee/Open8030), an
open-source firmware for the AR8030 radio chip, next to stock's. It is built
from source (Zephyr, with the Zephyr SDK's RISC-V compiler; Buildroot downloads
both) with board profiles reverse engineered from the stock radio firmware,
which the `open8030-profiles` package downloads (one archive, checked by its
hash and each file by the archive's SHA256SUMS). To build with a local copy
instead - new or changed profiles, from an Open8030 checkout's `.local/`:

```sh
scripts/open8030-private.sh ../Open8030   # -> vendor/open8030 (git-ignored)
make OPEN8030_PRIVATE_DIR=$PWD/vendor/open8030 ...
```

The images then carry:

- the goggle gets `/lib/firmware/open8030-vrxpro-usb.img` and its radio config,
  and runs it by default; kestrel-gnd's RADIO > VRX Radio Firmware switches
  between it and stock's at the next radio start (the goggle's radio only, not
  the air unit's).
- the air unit gets `/usrdata/fpv/air/open8030/open8030-ap.img`. A Lite or Lite+
  uses it when `/usrdata/fpv/air/open8030/always` exists, which the air image
  ships (`BR2_PACKAGE_OPEN8030_AIR_DEFAULT=y` in `ascentlite_defconfig`); remove
  the file over ssh to go back to stock's. Both ends must run the same firmware
  family: an Open8030 air unit needs an Open8030 goggle.

`OPEN8030_OVERRIDE_SRCDIR` (in the board output directory's `local.mk`) builds a local Open8030 checkout
instead of the pinned commit.

## 3. Build

```sh
./build.sh            # defconfig -> full Buildroot build -> SD image
```

Sub-commands for iterating:

```sh
./build.sh config     # (re)generate the Buildroot .config from the defconfig
./build.sh kestrel    # rebuild only kestrel into the sysroot
./build.sh image      # re-assemble the image (rootfs already built)
./build.sh air        # the air unit's image, into output/ascent-lite/ (see below)
```

The VRX Pro images are in `output/vrxpro/images/`:

- `sdcard.img` — the raw image, for `dd`
- `sdcard.img.xz` — the same image compressed, for balenaEtcher or Raspberry
  Pi Imager, and the one to copy around

`COMPRESS=0 ./build.sh` skips the `.xz` when you're iterating and only `dd`.

Each board uses a separate output directory:

| Build command | Output directory |
| --- | --- |
| `./build.sh` | `output/vrxpro/` |
| `./build.sh air` | `output/ascent-lite/` |
| `./build.sh ascent-vrx` | `output/ascent-vrx/` |

Each contains its own `.config`, `build/`, `host/`, `target/` and `images/`.
Build outputs are Git-ignored. Run package and configuration commands against
that board's directory, for example `make -C output/vrxpro menuconfig`, after
`./build.sh config`. Put local package overrides in that directory's `local.mk`.

Older checkouts used `buildroot/output/`, `output-air/` and `output-ar9311/`.
`output/ascent-gnd485/` was also used before the product-name rename.
Those folders are left untouched and remain ignored. Start a fresh build at the
new location; moving an existing Buildroot output can leave embedded absolute
paths pointing to the old directory. Copy any intentional `local.mk` overrides
separately. Release archives continue to be assembled under `out/`.

## 4. Flash and boot

See [INSTALL.md](INSTALL.md) for flashing, first boot, and recovery back to
stock. The easy way is balenaEtcher with `sdcard.img.xz`; from a Linux shell:

```sh
sudo dd if=output/vrxpro/images/sdcard.img of=/dev/sdX bs=4M conv=fsync
# If the card is larger than the image, extend the backup GPT:
sudo sgdisk -e /dev/sdX
```

## How the image boots

The three-partition SD layout (a FAT fallback, the ext4 root, and a FIT boot
partition) and the loader/init sequence it needs are all handled by
`boot/mk-sd-image.sh`, using boot artifacts extracted from your own device.
You don't need to assemble any of it by hand — `./build.sh` does it.

## The air unit

fpvOS also builds firmware for the Caddx Ascent Lite and Lite+ air units
(Hi3516CV610), as an image the Caddx PC tool or the
[fpvOS Flasher](https://gehee.github.io/fpvOS_flasher/) flashes, and can always
reflash with Caddx's own update.

```sh
scripts/extract-vendor.py      # also saves the stock Ascent_H_Sky_*.img to vendor/stock/air/
./build.sh air                 # -> output/ascent-lite/images/Ascent_H_Sky_18_21_10.img
./build.sh air kernel          # just the toolchain and the kernel
boot/ascent-kernel-check.py    # compare our kernel with the stock one
```

**The image** is the stock one with a new app volume (`/usrdata`): U-Boot, env,
kernel and rootfs stay byte-identical to stock. The app volume is the stock
one plus `fpv/air/`, holding kestrel-air, the CV2004 and OS02K10 sensor drivers (they read their
tuning from the stock air app, which stays, and kestrel-air picks the one that
matches the camera),
ar_libre's driver and library, and the HiSilicon MPI libraries kestrel-air
links. A hook added to the stock
`fpv_run_cx482.sh`, after everything the PC tool needs, runs `air/start.sh`,
which starts kestrel-air where the stock script would start the stock air app.
`touch /usrdata/fpv/air/disable` on the unit gives the stock app from the next
boot.

**Lite or Lite+:** one stock image serves both, and so does ours. The stock
board script tells them apart by a voltage on the board (board type 482 is the
Lite, 472 the Lite+), and `air/start.sh` follows it: the Lite+ gets its own radio
chip firmware and config, as on stock, and kestrel-air is told the board type
(`KA_BOARD_TYPE`) for what its air app does differently (power offsets, the
high-power front end). Any other board type keeps the stock air app. [`boot/mkascentimg.py`](../boot/mkascentimg.py) packs it, and refuses an
app volume that would lose the PC tool's updater.

**SSH**: `air/start.sh` starts a statically linked dropbear on port 22, with
the login `root` / `root` by default. `FPVOS_AIR_ROOT_PASSWORD` sets another
password at build time, and an empty one (`FPVOS_AIR_ROOT_PASSWORD=
./build.sh air`) turns password login off. `FPVOS_AIR_SSH_KEYS` adds public
keys (`FPVOS_AIR_SSH_KEYS=~/.ssh/id_ed25519.pub ./build.sh air`); an image
built with keys carries them, so do not share it. The stock rootfs is not
changed: the password goes in a copy of `/etc/shadow` mounted over it at boot.
The unit speaks network once its USB link is switched from the Caddx serial
gadget to network, at 192.168.2.1, with a DHCP server for the computer. The
host key is made on the first boot, in the app volume.

The MPI libraries are proprietary and only exist prebuilt (the stock firmware
links them statically into its own app); `hi3516cv610-sdk` fetches them and
the two sensor drivers as one archive, pinned by commit and checked by hash.
They are the same SDK build as the stock kernel modules the image keeps.

**The kernel** in the image is the stock one, byte for byte. The build still
builds a kernel, kernel.org's 5.10.221 (the stock version) with
[`linux.defconfig`](../br-external/board/ascent-lite/linux.defconfig): it is
what `arlink.ko` is built against and where the toolchain's headers come from,
and nothing boots it. The config is HiSilicon's Hi3516CV610 SDK 1.0.2.0 one
(the SDK's `hi3516cv610_defconfig` plus
[`linux.fragment`](../br-external/board/ascent-lite/linux.fragment)) without
the options only HiSilicon's tree has, so `arlink.ko` gets the stock modules'
vermagic; built against either tree it is the same file, byte for byte. Two
limits: HiSilicon adds fields to `struct mmc_host` after `detect_change`, so a
driver that reads past them needs HiSilicon's tree, and so does a kernel of our
own to boot (its NAND, MMC and USB drivers; the device tree, decompiled from
the stock one, and `ascent-kernel-check.py` are for that).

## Troubleshooting

- **`vendor blobs missing`** — run `extract-vendor.py` (step 2); it prints what
  it couldn't find.
- **Buildroot fails on first package** — confirm you cloned the exact pinned
  version from `br-external/BUILDROOT_VERSION`.
- **Boots to a black screen** — almost always the loader; confirm
  `output/vrxpro/images/uboot-patched.bin` exists (the fpvos-bootchain
  package makes it from `vendor/stock/uboot.img`).

## AR9311 / Ascent Gnd485

The experimental `ascentvrx_defconfig` (`./build.sh ascent-vrx`) builds Linux 6.18 with decoder, HDMI,
SDIO radio and USB recovery/update support. See the [AR9311 board guide](AR9311.md)
for dependencies, building, RAM boot, NAND installation and known limitations.
Shared SoC support lives under `br-external/board/common/ar9311`; Gnd485 wiring,
display and NAND policy live under `br-external/board/ascent-vrx`.
