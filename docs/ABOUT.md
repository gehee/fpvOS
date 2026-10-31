# About fpvOS

Where the project comes from, what is open and what isn't, how the repositories
fit together, and where it is going.

## Why

Digital FPV goggles ship as sealed appliances: the link, the on-screen display,
the recording and the menus are all frozen behind a vendor firmware you can't
read, fix or extend. FPV outgrew that model years ago on every other front:
**Betaflight** opened the flight controller, **EdgeTX** opened the radio,
**ELRS** opened the control link. The goggle is the last closed box in the
chain. fpvOS opens it.

**The focus is the experience, not the plumbing.** Open FPV so far has largely
been a story about connectivity and interoperability: bridging protocols,
getting one vendor's link to talk to another's. ELRS and Betaflight changed how
a quad flies and links, but the screen you stare at for the entire flight
hasn't gotten the same attention. fpvOS starts from that end: what you *see* in
the goggles, how the HUD reads, how the video feels, how recording and the
menus behave. Because it renders on a real GPU and owns the whole screen, an
open goggle has a real shot at feeling as good as, or *better* than, a sealed,
fully integrated system, by making the one thing you look at all flight better
than any locked firmware will ever bother to.

## What's open, and what isn't

Everything in these repos is GPLv3 and builds from source: the kestrel
applications, the radio's host stack ([ar_libre](https://github.com/gehee/ar_libre),
written from observed behaviour), the kernel, the graphics stack. A few pieces
belong to Caddx, Artosyn, Rockchip and HiSilicon and are not ours: the AR8030's
firmware, the stock boot chain, Rockchip's `librga`, and on the air unit the
Hi3516CV610's camera and encoder libraries (HiSilicon's MPI), which only exist
prebuilt. Not one line of them lives in the repositories.
`scripts/extract-ascent-vrx-pro-firmware.py` takes the goggle's from Caddx's own published
firmware when an image is built, and the air unit's libraries come in as one
archive, pinned by hash. Licences and the corresponding sources ship with every
release.

The radio chip, the AR8030, decides how the link modulates, schedules and
retransmits. It ran Artosyn's firmware until beta3; fpvOS now loads
[Open8030](https://github.com/gehee/Open8030), an open firmware for it, on the
goggle and on the fpvOS air unit, with the stock firmware one menu row away
(**RADIO › VRX Radio Firmware**). Its board profiles - the register defaults,
pins and keys, reverse engineered from Caddx's firmware - are published as
the `open8030-profiles` package's archive. The host driver and library that
talk to the radio, and everything on either side of it, are open.

## Repository layout

This repo builds the images. The applications and the radio stack live in
their own repos and are pulled in as Buildroot packages, each pinned to a
commit:

| Repo | What |
|---|---|
| [`gehee/kestrel-gnd`](https://github.com/gehee/kestrel-gnd) | **kestrel**, the goggle application: video, HUD, menus, DVR |
| [`gehee/kestrel-air`](https://github.com/gehee/kestrel-air) | the air unit application: camera, encoder, link |
| [`gehee/ar_libre`](https://github.com/gehee/ar_libre) | the AR8030 host stack on both ends: `arlink.ko` and the client library |
| [`gehee/fpvOS_flasher`](https://github.com/gehee/fpvOS_flasher) | the air unit flasher in the browser |

| Path | What |
|---|---|
| [`br-external/`](../br-external/) | Buildroot external tree: the goggle's and the air unit's defconfigs, packages, rootfs overlays |
| [`boot/`](../boot/) | SD-image assembly and the boot-chain recipes |
| [`scripts/`](../scripts/) | `extract-ascent-vrx-pro-firmware.py` fetches the vendor files; `release.sh` cuts a release |
| [`docs/`](.) | install, user, build and architecture guides |

To build the images yourself, see [BUILD.md](BUILD.md).

## Where this goes

fpvOS is a beta for one goggle, and it is meant to grow into a community-owned
platform like Betaflight and EdgeTX became, where a good idea from anyone can
end up on everyone's goggles. That depends on everyone it takes: pilots who fly
it, contributors who build on it, and the companies behind the hardware.

**For manufacturers.** If you build around the **Artosyn AR8030**, fpvOS shows
what your goggle could ship with instead of a pilot experience written from
scratch. It runs on **Rockchip RK3568**: H.264/H.265 decode on the hardware
VPU, with decoded frames handed to the display as DMA-BUFs and scanned out
without a copy, the foundation of a low glass-to-glass latency pipeline. With
your own Artosyn and Rockchip BSP, a port would be a Buildroot board directory:
your defconfig, your bring-up script, your baseband config, your button map. If
that's interesting, [get in touch on Discord](https://discord.gg/CXhNKYFF2v).

## Contributing

This is a young project with a big target, which is the best time to join. Good
first ground to break:

- **New hardware**: another AR8030 goggle you can get a shell on
- **HUD & UX**: it's all open; make the FPV overlay you always wanted
- **Themes**: [request one](https://github.com/gehee/kestrel-gnd/issues/new?template=theme_request.md) with a preview, or vote on the others
- **Video pipeline**: latency, codecs, the decode path
- **Docs**: clear flash and HUD docs save the next pilot an evening

Open an issue to say hi, or a PR to dive in. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## Thank you

To **Artosyn**, for the AR8030, a digital video link good enough that the
hardware was never the limit, only the software around it. And to **Caddx**,
for building the VRX Pro and the air units around it, and for publishing their
firmware for anyone to download. fpvOS stands on both, and wouldn't exist
without such great systems to build on.

## License

**GPLv3** for all code, the same copyleft Betaflight, EdgeTX, iNav, and ELRS
chose, so improvements flow back to everyone. Bundled fonts keep their own
licenses, shipped next to them: Chakra Petch under the SIL OFL, DejaVu under
the Bitstream Vera license. The idle-screen background
(`etc/kestrel/background.png` and `background.mp4` in the rootfs overlay) was
generated for fpvOS with Google Gemini; it contains no third-party footage and
ships under the same terms as the rest of the repository. The proprietary
files `extract-ascent-vrx-pro-firmware.py` fetches are **not** covered by this license.
