# Contributing to fpvOS

fpvOS is early and the target is big — the best possible time to get involved.
Whether you fly the VRX Pro, have another AR8030 goggle, or just want to hack on
an open HUD, there's room.

## Ground rules

**Never commit vendor firmware.** The AR8030 baseband stack, the Mali GPU
driver, and the Rockchip media libraries are proprietary. `scripts/extract-vendor.py`
takes them from Caddx's public stock firmware download (or from your own goggle
with `--from-device`) into `vendor/`, where everything but `vendor/MANIFEST` is
git-ignored. Do not add them, do not vendor an SDK header, do not check in an
extracted firmware image. Interfaces to proprietary code are documented from observed
behavior in [`docs/`](docs/), never copied. This keeps fpvOS legally clean, and
it's non-negotiable.

**GPLv3.** By contributing you agree your changes ship under the project
license. Keep it copyleft-compatible.

## Two repositories

- **[fpvOS](https://github.com/gehee/fpvOS)** (this one) — the image: Buildroot
  config, boot chain, init scripts, WiFi, build and release tooling.
- **[kestrel-gnd](https://github.com/gehee/kestrel-gnd)** — the ground
  application: video, HUD, menus, DVR, the web page.

A change to what's on screen is a PR to kestrel-gnd. fpvOS builds kestrel at
the revision pinned in `br-external/package/kestrel/kestrel.mk` (`KESTREL_PIN`),
so once a kestrel change is merged, a one-line fpvOS PR moves the pin.

## Getting set up

1. `git clone --recurse-submodules https://github.com/gehee/fpvOS.git`
   (Buildroot comes down pinned).
2. Fetch the vendor blobs: `scripts/extract-vendor.py` (downloads the stock
   firmware once and caches it).
3. Build: `./build.sh` — see [docs/BUILD.md](docs/BUILD.md). About 20 minutes
   from scratch on a recent machine; tested on a clean Ubuntu 24.04.
4. Flash `sdcard.img.xz` with balenaEtcher (or `sdcard.img` with `dd`) and boot
   it — see [docs/INSTALL.md](docs/INSTALL.md).

## Iterating on kestrel

No need to reflash for an app change. Build your kestrel checkout into the
Buildroot tree, then swap the binary on a running goggle over the USB link:

```sh
# in fpvOS; dirclean matters - kestrel-rebuild re-uses the last sources it copied
make -C buildroot BR2_EXTERNAL=$PWD/br-external \
     KESTREL_OVERRIDE_SRCDIR=/path/to/kestrel-gnd kestrel-dirclean kestrel

# onto the goggle (root password: fpvos). Piped, not scp: the goggle has no
# sftp-server, which current scp needs.
cat buildroot/output/target/usr/bin/kestrel-gnd |
  ssh root@192.168.3.1 'cat > /tmp/kestrel-gnd && chmod +x /tmp/kestrel-gnd &&
    { /etc/init.d/S70kestrel stop; cp /tmp/kestrel-gnd /usr/bin/; } &&
    /etc/init.d/S70kestrel start'
```

The log is `/var/log/kestrel-gnd.log`. No aircraft handy? `kestrel-gnd --demo=1`
(or `demo_mode` in the settings) drives the whole HUD from a simulated flight.

## Good places to start

- **New hardware** — another AR8030-class goggle you can get a root shell on.
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the documented baseband ABI
  in kestrel-gnd (`artosyn/bb_client.h`) are your map.
- **HUD & UX** — it's all in the [kestrel repo](https://github.com/gehee/kestrel-gnd)
  (`hud_*.cpp`, `osd.cpp`). Demo mode makes this a tight loop.
- **Video pipeline** — latency and the decode path (`vdec/` in the kestrel repo).
- **Docs** — clear docs for building, flashing, and the HUD save the next
  person days. Add to `docs/`.

## Submitting

- Open an **issue** to discuss anything non-trivial before a big PR — saves
  everyone rework.
- Keep PRs focused; one change per PR.
- Say how you tested. "Flies on my VRX Pro" / "verified in `--demo`" / "built
  clean" all help. We can't merge display changes we can't see working.
- Match the surrounding code style. The HUD code in particular leans on
  comments that explain *why* a number is what it is — keep that up; those
  numbers were expensive to find.

## A note on hardware safety

fpvOS boots from SD and never writes the goggle's internal NAND, so it's
reversible by pulling the card. (It only reads it: at boot, the pairing list
stock saved is merged in read-only, so paired air units carry over.) If you're
poking at the boot chain or the baseband, keep it that way — nothing in a PR
should write to NAND.

Welcome aboard.
