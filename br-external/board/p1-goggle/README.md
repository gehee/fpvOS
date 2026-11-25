# BETAFPV P1 goggles

The `p1-goggle` profile supports the RAM-boot and NAND-install platform for the AR9311 P1
receiver. It reuses the Ascent VRX's shared kernel configuration, patches,
GPIO/MMC package and USB gadget service. Board wiring lives in its own DTS;
it does not select the Ascent HDMI profile or NAND update backend.

```sh
./build.sh p1-goggle config
KESTREL_NATIVE_IMAGE="$P1_RUNTIME_SQUASHFS" ./build.sh p1-goggle all
```

Artifacts are in `output/p1-goggle/images/`: `Image`,
`betafpv-p1-goggle.dtb`, `rootfs.cpio.gz`, the guarded `kernel.img`, and
`fpvos-p1-goggle.fwu`. The bundle uses the board-specific updater backend;
a graphical flasher target is not registered yet.

The board has 256 MiB DRAM. The initial configuration preserves stock's
148 MiB Linux / 108 MiB reserved split. Of the reserved range, 107 MiB
is codec DMA memory and the top 1 MiB remains reserved for the RAM loader. The two CPUs use the AR9311 SPL handshake;
a diagnostic loader that parks the second CPU must supply `maxcpus=1`.
USB Ethernet uses `192.168.3.1/24`, as every fpvOS goggle, with SSH `root:root`; the computer gets an address from .200-.209. The USB identity is
`fpvos-p1-goggle`, distinct from Ascent VRX and P1 Air.

The NAND layout preserves the stock bank and installs fpvOS into the other
bank's kernel, DTB and userapp (the bank already holding fpvOS - by its bundle
or its kernel - else the one booted stock does not run from; the choice is in
`src/ar9311-banks.h`). SPL, bootloaders, vendor data and factory calibration are exposed
read-only; both banks' kernel/DTB/userapp are writable, guarded by the
updater's checks rather than the DT. The updater changes the boot
selection only after verifying all three fpvOS components. User data holds
recovery state; factory calibration stays read-only. The shared SD service
mounts an existing FAT, exFAT or ext4 card at `/mnt/sd` without formatting or
repairing it. Kestrel records received video to `/mnt/sd/fpvos/recordings`;
settings and pairing still remain in RAM.
GPIO100 is the shared SD/panel supply and stays enabled; Ascent's SD voltage
selection and radio reset wiring are not reused.

The display profile selects the QY45043A0 panel, its stock internal raster and
DSI PHY tables. PWM backlight starts off and is controlled through
`/sys/class/backlight/backlight/brightness` (0–10). Display bring-up currently
inherits early clocks and pinmux from stock, including scan-strap power-on state.
The profile exposes only nominal 1920×1080; it does not select Ascent HDMI modes.

Remaining integration: extended button regression and status
LED, persistent pairing/settings,
and broader recovery/updater qualification. The P1 stock decoder blob differs from the Ascent blob; compatibility
must be tested before selecting either for a release.

## Initial hardware validation

Linux 6.18.36 and this rootfs have booted on the goggles through a temporary
stock-Linux RAM loader. USB Ethernet/SSH, a 16 MiB memory test, SD enumeration
and read-only exFAT mounting passed. The initial test exposed NAND as a single read-only partition;
reads of the active bootloader, environment, kernel and DTB matched stock.

That initial test used one CPU and inherited stock hardware initialization.
Subsequent direct U-Boot RAM boot starts both CPUs and the embedded recovery
environment without first running stock Linux.
Subsequent radio validation is described below. The exact-stock diagnostic loader is a local bench tool,
not a supported installation method. Use neither the Ascent VRX nor P1 Air
flasher profile for these goggles.

## Internal display

The QY45043A0 panel driver, shared VO/DSI controller and PWM backlight have
passed a RAM-boot color-bar test, with stable, correct orientation confirmed
on the goggles. All 519 panel commands and 47 D-PHY table entries were checked
against the connected device's stock software/registers. The profile retains
the stock internal raster; a 15-second page-flip test settled at 60.00 Hz. This does not measure
camera-to-display latency. Hardware video and UI integration remain separate work.

The pixel clock is explicitly derived from the MIPI PLL. The stock clock
selector depends on prior vendor initialization and produces roughly 31 Hz
when booting fpvOS directly, causing rolling corruption. The launcher also
unblanks backlight power: setting brightness alone leaves a cold-started
backlight off.

For a manual test, run `modetest -M artosyn-vo -c` to find the DSI connector,
then `modetest -M artosyn-vo -s <connector-id>:1920x1080 -F smpte` and set
`/sys/class/backlight/backlight/brightness` to 5 and
`/sys/class/backlight/backlight/bl_power` to 0 (unblank). Keep modetest's input open
while viewing. Backlight level 0 turns it off; the shared SD/panel supply stays on.

When changing the kernel configuration in an existing output directory, clean
external modules before building the image to avoid stale module objects:

```sh
make -C output/p1-goggle ar9311-mmc-dirclean
KESTREL_NATIVE_IMAGE="$P1_RUNTIME_SQUASHFS" ./build.sh p1-goggle all
```

## Decoder development

The shared Wave5 driver uses the goggles' unmodified decoder firmware,
installed as `/lib/firmware/artosyn/p1-goggle-chagall.bin`. The
`ar9311-firmware` Buildroot package downloads BETAFPV's pinned P1_GND 1.0.36
release, verifies its SHA-256, extracts `usr/bin/chagall.bin.gz` from
userapp0's UBI/SquashFS filesystem, decompresses it and verifies the output.
This is part of the normal package build; no device dump or pre-build step
is needed. The official source is linked from
[BETAFPV's goggles firmware page](https://support.betafpv.com/hc/en-us/articles/53798961852185).

The extracted SHA-256 is
`308b96351168cc7dbbe936de1490f9ab553aa9ae7e1679d8e9a8c4ab8cd5bf86`,
identical to the hardware-tested stock blob. `ar9311-media-start` verifies
that hash again before loading Wave5 at startup. Downloads stay in the
Buildroot cache; Git contains the recipe and hashes, not vendor binaries.
The package marks the firmware non-redistributable; extraction does not
establish permission to redistribute it in published images.

The decoder exposes `/dev/video0`. `ar9311-decode-test` checks bounded Annex-B
H.264/HEVC clips, and `ar9311-play` feeds decoded I420 buffers directly to the
panel through DMA-BUF. Neither tool requires SD storage or NAND writes.
The driver resets inherited AR9311 codec firmware on probe, since the stock
Linux RAM handoff can leave the codec running with old buffer addresses.

Hardware validation: H.264 and H.265 each decoded eight 1920×1080 frames
byte-for-byte equal to host software references. Both codecs also played
600 frames at 59.9 fps with zero late frames and zero CPU pixel copies,
including a repeat after a fresh stock-to-fpvOS handoff. These are local test
clips, not an end-to-end radio/video test. The driver currently logs a
`result not ready: 0x800` message during these otherwise successful runs;
that diagnostic remains recorded for follow-up.

## Kestrel UI

Build Kestrel Ground with `KESTREL_HAL=ar9311` and
`KESTREL_BOARD=p1goggle`, using its native build instructions and the normal
font/background inputs. Package that build with Kestrel's
`tools/package_ascent.py`, then set `P1_RUNTIME_SQUASHFS` to the resulting
runtime before running the build command above. This reuses the existing
native runtime package; the image contains the app and baked UI assets.
When replacing the runtime in an existing output directory, run
`make -C output/p1-goggle kestrel-native-dirclean` before rebuilding.

The init service mounts the runtime read-only and supervises Kestrel. The
board defaults in `/etc/default/kestrel-native` set backlight level 5 and
enable radio when both the radio and decoder are ready. Offline UI is the
fallback if either is unavailable. Preferences are RAM-only
at this stage. The P1 evdev backend uses the on-chip ADC keypad. No Ascent keypad or beeper backend is selected.

Navigate remotely over SSH, for example:

```sh
/opt/kestrel/bin/kestrel-gnd --control /run/kestrel-gnd/control --send-key menu
/opt/kestrel/bin/kestrel-gnd --control /run/kestrel-gnd/control --send-key down
```

Radio reception and decoder provisioning are integrated. Persistent preferences
remain separate work.

## Keypad

The shared IIO ADC provider exposes channel 0 to Linux `adc-keys`. The P1
DTS uses the stock ladder levels: Bind 200 mV, Back 400, Record 600,
Up 800, Left 1000, Right 1200, Enter 1400, Down 1600; idle is 0 mV.
The ADC calibrates gain with the nominal 900 mV internal reference while
preserving zero code as ground (2025 mV full-scale fallback if calibration fails). Physical UI input has been confirmed by the user; a recorded per-key voltage
and event matrix remains follow-up validation.
ADC control and data resources exclude the MMC PLL registers in the same
address block. Do not enable a separate temperature driver that accesses
this ADC concurrently without shared locking.

Kestrel finds `p1-goggle-keys` by input-device name rather than event number.
It debounces for 40 ms, arms after release, and repeats only directional
buttons. Enter opens/selects, Back returns, Record requests recording;
short Bind requests pairing only when radio is enabled. Long Bind does not
flash firmware. Physical pairing-button operation has been confirmed; pairing
persistence across reboots remains to be implemented.

## Open8030 radio

The profile selects `betafpv-p1-goggle.c` in DEV/SDIO mode with early pins,
explicit I/O domains and optional radio-local factory storage. The host uses
the shared AR9311 MMC, radio and calibration packages. GPIO23 is the radio
reset; the board DTS enables MMC0 for SDIO. P1 register defaults, pin wiring
and RF gain tables remain board-specific. The channel and protocol settings
match the existing fpvOS air/ground configuration.

`S43factory` verifies the original factory partition geometry and read-only
MTD/UBI state, then mounts `/factory` read-only. `S44ar9311-radio` merges
`/factory/ar8030_pwr.json` with the board template into
`/run/ar9311-radio/config.json` before uploading Open8030 to radio RAM.
Calibration failure leaves the radio stopped; this board does not enable
an uncalibrated fallback. Device identity comes from radio OTP, not a
unit-specific MAC embedded in the template.

The board profile, Open8030's `profiles/betafpv-p1-goggle.c`, is in the
Open8030 revision the package pins; no local override is needed. To try an
Open8030 checkout of your own, set `OPEN8030_OVERRIDE_SRCDIR = /path/to/Open8030`
in `output/p1-goggle/local.mk`.

A RAM-boot test with a P1 Air running fpvOS passed SDIO startup, association,
all ten control acknowledgements and reception of 3.07 MB over 20 seconds.
With the decoder provisioned, Kestrel received live HEVC video and decoded
more than 10,000 frames without decoder drops, queue overflows or capture
errors. Radio sequence gaps and damaged-packet counters were nonzero; this
is functional bring-up, not a loss-free or range qualification. Pairing was
supplied temporarily for this test; the user subsequently confirmed physical
pairing-button operation. Persistence remains to be implemented. The UI falls back to offline operation when the
radio or decoder is unavailable.

## NAND installation and recovery

Initial installation requires booting the guarded kernel and board DTB into
RAM through the verified P1 USB downloader path. The embedded recovery root
provides the USB updater without an SD card or external initramfs. The goggles
backend deliberately rejects installation from stock Linux; do not substitute
another board's installer.

Use `tools/fpvos-update/client.py --board p1-goggle --port <goggles-port>`
with `info`, `clean`, then `install output/p1-goggle/images/fpvos-p1-goggle.fwu`.
The installer selects the stock bank before writing the target bank, verifies
readback, and selects the target last. The installed kernel contains a small
recovery root that validates and unpacks the full rootfs bundle from the
booted bank's userapp. A missing or
invalid bundle leaves the USB recovery service running. `clean` enters this
recovery environment for subsequent updates; `stock` selects the preserved
stock bank without rewriting it.

A pre-kernel watchdog guard counts consecutive failed boots and requests the
stock U-Boot USB downloader after the third failed attempt. Its observed USB
window is approximately 20 seconds before normal boot resumes, so the host
recovery loader must already be waiting. Normal reboots
clear that count. This cannot recover an unreadable kernel or damaged SPL,
U-Boot or partition table; retaining a flash backup is still necessary.
