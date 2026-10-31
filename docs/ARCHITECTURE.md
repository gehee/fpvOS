# Architecture

How fpvOS is put together, and where to look when you want to change something.

## The stack

```
  ┌─────────────────────────────────────────────────────────┐
  │  kestrel-gnd            the fpvOS ground application       │
  │    video decode ─ HUD/OSD render ─ DVR ─ menu ─ settings   │
  └───────────┬───────────────────────────────┬───────────────┘
              │ bb_client.h (our ABI decl)     │ GLES / DRM / MPP / RGA
  ┌───────────▼───────────┐       ┌────────────▼──────────────┐
  │ libar8030_client.so    │       │ Mesa (Panfrost) · MPP ·   │
  │ + arlink.ko (ar-libre) │       │ librga (vendor)           │
  └───────────┬───────────┘       └───────────────────────────┘
              │ AR8030 baseband (USB), running Open8030 (or Artosyn's firmware)
        ┌─────▼─────┐
        │  air unit │  H.264/H.265 video + telemetry over the digital link
        └───────────┘
```

kestrel, the radio's host stack (ar-libre), the kernel (see
[KERNEL.md](KERNEL.md)) and the GL stack are open source and built from
source. What is still proprietary is listed under the vendor boundary below;
fpvOS talks to it through documented interfaces, never by including its code.

## kestrel — the application

kestrel lives in its own repo, [`gehee/kestrel-gnd`](https://github.com/gehee/kestrel-gnd);
this repo pulls it in as a Buildroot package. The file paths below are relative
to that repo. One process, `kestrel-gnd`, laid out roughly as:

| Area | Files | Does |
|---|---|---|
| Link source | `artosyn/ar8030_source.cpp` | Opens the baseband, configures the link, reads video packets and telemetry |
| Baseband ABI | `artosyn/bb_client.h`, `bb_ioctl_v2.h` | Our own declarations of the vendor client library's C ABI — no vendor SDK |
| Watchdog | `artosyn/bb_watchdog.cpp` | Recovers a wedged `bb_socket_open()` |
| Video decode | `vdec/vdec_rk.cpp`, `vdec/vdec_ffmpeg.cpp` | Rockchip MPP hardware path, FFmpeg fallback |
| Renderer | `renderer.cpp`, `drm.cpp`, `drm/` | GLES on DRM/GBM; composites the OSD plane over the video plane |
| HUD | `hud_canopy.cpp`, `hud_lock.cpp`, `hud_theme.cpp`, `osd.cpp` | The canopy HUD, signal-lock/idle animations, the whole on-screen display |
| Menu | `hud_menu.cpp` | On-goggle settings UI, driven from the goggle buttons |
| Betaflight OSD | `msp_osd.cpp`, `betaflight_glyphs.cpp` | MSP-DisplayPort overlay from the flight controller |
| DVR | `dvr.cpp`, `screen_tap.hpp`, `webstream.cpp` | Records the FPV stream (a lost picture replaced by a copy, `utils/hevc_repair.cpp`), or the screen (video and HUD rebuilt by the RGA, H.265 at up to 100 fps); the WiFi spectator page gets the same screen, encoded in H.264 |
| Settings | `settings.cpp` | `/etc/kestrel/kestrel-gnd.yaml` |

The HUD has four overlays, picked in the menu or with `hud_overlay` in the
settings: **OFF** (only the Betaflight OSD), **CANOPY** (the default), **ARENA**
and **ARENA FULL** (ARENA plus its diagnostic rows).

## The vendor boundary

The image needs three proprietary pieces, none of which live in this repo:

- **The AR8030's stock firmware** (`bb_demo_cx485_2PA.img`) and its baseband
  config (`bb_config_gnd_pro.json`). By default the radio runs
  [Open8030](https://github.com/gehee/Open8030) instead, built from source by
  the `open8030` package; the stock files are what `arlink.ko` uploads when
  **RADIO › VRX Radio Firmware** says STOCK. Open8030's board profiles come
  from the `open8030-profiles` package (see [BUILD.md](BUILD.md)). The host side is fpvOS's own: the `ar-libre`
  package's `arlink.ko` and its `libar8030_client.so`, a drop-in for Artosyn's
  library with no daemon. kestrel declares only the ~15 ABI functions it calls
  in `bb_client.h`, documented from observed behavior, and links the library
  at runtime.
- **The stock boot chain** — U-Boot, ARM Trusted Firmware and OP-TEE, adapted
  for the SD card by `boot/mkbootchain.py` (see The image).
- **`librga`** — Rockchip's 2D scaling/blitting library. kestrel's screen
  recorder blends each recorded frame with it (the decoded picture and the
  HUD, into the encoder's input); its headers are kept in kestrel-gnd's
  `include/rga`, since the firmware ships the library only.

Hardware video *decode* is deliberately not on that list: `librockchip_mpp`
is genuinely open source (Apache-2.0/MIT) and built from source by
[`br-external/package/rockchip-mpp/`](../br-external/package/rockchip-mpp/),
pinned to the commit kestrel's decoder was validated against.
`extract-ascent-vrx-pro-firmware.py` does still pull a copy of the vendor `librockchip_mpp`,
but only as a documented fallback - `fpvos-vendor-libs.mk` explicitly skips
installing it so the from-source build is never silently overwritten.

`scripts/extract-ascent-vrx-pro-firmware.py` pulls the proprietary pieces (and that MPP
fallback) from firmware the user owns; they're merged into the image at
build time by `br-external/board/ascent-vrx-pro/post-build.sh`. See
[`vendor/MANIFEST`](../vendor/MANIFEST).

## The image

Built by Buildroot (`br-external/`, a `BR2_EXTERNAL` tree) plus
`boot/mk-sd-image.sh`, which assembles a three-partition SD card **rootless**
(no loop mounts) from Buildroot's `rootfs.ext2` and the vendor boot chain:

- **p1 `bootfat`** — FAT, an extlinux fallback boot path
- **p2 `rootfs`** — the ext4 root
- **p3 `boot`** — the FIT that U-Boot actually boots from

The boot chain is the stock U-Boot with the kernel built from source (see
[KERNEL.md](KERNEL.md)), put together at build time by `boot/mkbootchain.py`
(the `fpvos-bootchain` package) from the stock boot images in your own
firmware download: three U-Boot hooks stubbed out so it can boot from SD, and
the stock device tree, edited to mount the card and for the newer kernel.

## Reverse-engineering notes

The interfaces to proprietary code — the baseband RPC and the camera/air
control protocol — are documented from observed behavior; that's the reference
behind the numbers in `bb_client.h`. When something low-level doesn't behave,
`ar8030_source.cpp`'s own logging (link state, MCS, RF setup) is the first
place to look.
