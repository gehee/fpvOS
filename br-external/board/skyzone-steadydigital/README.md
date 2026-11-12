# Skyzone SteadyDigital (AR9311)

Experimental board on the shared AR9311 platform (`board/common/ar9311`, the
Ascent VRX's kernel, codec and display drivers): Linux 6.18, Wave5 decoding,
VO/DSI to the board's LT9611 HDMI bridge, the AR8030 radio over SDIO with
Open8030, USB networking and the native Kestrel receiver. Two images: a RAM
image, which writes nothing to flash, and a flashable one for NAND bank B
(below), which leaves stock in bank A.

```sh
./build.sh skyzone-steadydigital config
OPEN8030_PRIVATE_DIR=$PWD/.local/open8030-private OPEN8030_CONFIG_DIR= \
KESTREL_NATIVE_IMAGE=/abs/path/runtime.squashfs ./build.sh skyzone-steadydigital
```

`OPEN8030_PRIVATE_DIR` holds `skyzone-steadydigital.c` (the board profile
recovered from the box's own firmware: 20 pin records, I/O domain bank 2, its
FCH key table) and Open8030's `bb_defaults.inc`. Open8030's own profile for
this box (`profiles/steadyview-vrx.c`) is an older 10-record one that does not
link on this board. Leave
`OPEN8030_CONFIG_DIR` empty so the ground configuration is made from the stock
VRX Pro one as usual. The Kestrel runtime is kestrel-gnd's native `ar9311`
build packaged by `tools/package_ascent.py`.

## RAM boot

The box keeps its vendor SPL and U-Boot. Enter U-Boot from a running system
(stock: `devmem 0x0A106138 32 0x1` then a watchdog reset; the UART at
1152000 8N1 needs Ctrl-C and Enter to stop autoboot), set temporary variables
only (never `saveenv`), start `artosyn_hid_upgrade 0`, then:

```sh
T=scripts/ar9311-ram-transfer.py
python3 $T --board skyzone-steadydigital write-verify 0x24400000 output/skyzone-steadydigital/images/kernel.img --report k.json
python3 $T --board skyzone-steadydigital write-verify 0x22080000 output/skyzone-steadydigital/images/skyzone-steadydigital.dtb --report d.json
python3 $T --board skyzone-steadydigital write-verify 0x26000000 output/skyzone-steadydigital/images/rootfs.cpio.uboot --report r.json
```

Ctrl-C on the UART, then `bootm 0x24400000 0x26000000 0x22080000`. The image
with Kestrel exceeds the Gnd485's 8 MiB initramfs window; `--board skyzone-steadydigital`
allows up to 0x29000000, below this board's ramoops and media pool.
The host loader device is U-Boot's `1d6b:0100`; non-root access needs a udev
rule. SSH is root:root at 192.168.3.104 (host side 192.168.3.10/32 with a route
to .104).

## Wiring

Vendor GPIO numbers (banks start at 0, 23, 45, 71, 77, 83, 94):

| Function | GPIO | Notes |
| --- | --- | --- |
| AR8030 reset | 23 | active low; the radio has no switched supply |
| Keys | 48 pair, 49 back, 50 up, 51 down, 52 left, 53 right, 54 enter | active low, polled (`steadydigital-keys`) |
| SD power / I/O rail | 68 / 100 | |
| LT9611 reset | 43 | the KAP reference DSI reset; stock leaves it high |
| Stock levels | 46 high, 55 low | function not identified |
| 5 V enable | 66 | stock `poweron.sh`; reads back low here |

The HDMI bridge is an LT9611 (ID `17 02 e2`) on I2C0 at 0x3b, driven with the
Gnd485's quirks: stock's own 1080p60 attribute uses the same raster and
928.8 Mbps lanes. Stock also ships an LT9711 library for another hardware
variant; its defaults (I2C3 0x41, GPIO107) do not apply to this unit.
Memory: stock gives Linux 148 MiB and the media pool the rest. CPUs use the
SPL `ar-spin-table` release, as on the P1. Flash is stock's A/B layout (below);
bank A (stock) and factory are read-only, bank B, the GPT and `usr_data` are
writable for the updater.

## Flashable image (bank B)

`./build.sh skyzone-steadydigital-flash` (with the same `OPEN8030_PRIVATE_DIR`,
`OPEN8030_CONFIG_DIR=` and `KESTREL_NATIVE_IMAGE` as the RAM build: the board's
Open8030 profile is not in the Open8030 repository) builds a NAND image instead
of the RAM one: `kernel.img` is a recovery kernel (a small fpvOS recovery initramfs, from
`package/fpvos-recovery`) and `fpvos-steadydigital.fwu` bundles it with the board
DTB and the main root (`rootfs.cpio.gz`). The updater backend
(`package/fpvos-update/backends/skyzone-steadydigital`) writes **bank B**
(kernel1/dtb1, and the bundle into the `userapp` UBI volume of userapp1) and
selects stock **bank A** while writing, so a power cut during the install still
boots stock. Factory calibration, the environment, U-Boot and bank A are never
written.

Every unit ships with the A/B GPT; nothing is converted. It is stock's own
table: one record at the start of `gpt0` (`gpt1` is erased), sized for the
128 MiB NAND, with a vendor table after it up to 0x4800. For each pair env,
uboot, kernel, dtb and userapp the boot chain starts the member with attribute
bit 47, and a slot change moves all five pairs together, so bank B boots
`env1`/`uboot1` (stock copies). The updater rewrites that record in place,
like the vendor's own flip, keeping the vendor table; `layout.h` accepts only
this exact table with one whole bank selected. The power must stay on during
that one block rewrite (there is no second record).

The main root is loaded from `userapp1` into RAM by the recovery `init` and
`switch_root`ed into; settings and pairing live in `usr_data` (shared), so a
reinstall of the same bank keeps them. Installing from the running fpvOS
recovery over USB is `fpvos-update`'s normal `clean` → `verify` → `install`
flow; `ar9311-nandctl stock` flips the active bank back to A.

**No-UART entry — open.** The stock Skyzone runtime has the Sirius
clean-system hook (`start_clean_system.sh`, `web:/usrdata/<script>` in
`/usrdata/sirius-clean-system-flag`), so dropping `fpvos-update` on `/usrdata`
over stock SSH and setting that flag can reboot into our RAM recovery with no
UART; that step is not built yet. Stock exposes the whole GPT as MTDs (the boot
chain rewrites dtb0's flat `mtdparts` and passes `ubi.mtd=17` for bank A), and
the updater recognises stock only while it runs from bank A.

An install writes bank B only when bank B is not what the unit runs: bank A is
the active one, or bank B already holds fpvOS. A unit whose own stock runs
from bank B (a vendor update moved it there) is refused before anything is
selected or written; so is a bank B bundle volume that cannot take the bundle.

## Status

Checked on hardware: both CPUs, HDMI picture (Kestrel UI) with monitor
detection, Wave5 decode at 60 fps, the radio running Open8030, binding to an
Ascent air unit and its video at 60 fps, Kestrel driven by the front keys.
The flashable image is installed and updated on hardware with
`tools/fpvos-update` (bank B, boot verified). An SD card with one filesystem
is mounted at boot and takes the recordings; DVR > Format SD Card makes any
card one exFAT partition. Not yet: a stock→fpvOS install over USB, and
removing the bring-up `/dev/mem`.

Also checked: 720p video at 720p60 and 720p120 without colour artefacts
(kernel patch 0031), 1080p scaled onto a 720p60 screen, the Video Mode list and
row, and decoder close failures that now free their memory (patch 0032, forced
failures on hardware).

## Known issues

Paused here on 2026-11-11; nothing below is solved.

- **Keep the screen at 60 Hz.** 720p120 corrupts the whole picture on the
  test monitor, at least when the video plane is scaled. That is the idle screen
  with no air unit (Kestrel scales its 1080p black picture to 720p) and
  presumably any 1080p stream on a 720p screen. Native 720p video at 720p120
  looked clean. Not investigated; the scaler at 120 Hz is the prime suspect.
- **720p100 shows half a grey screen** on the same monitor, which lists neither
  720p100 nor 720p120 in its EDID. Both modes are offered only with
  `kestrel-gnd --force-display`, which the image does not set.
- **No 1080p100/120 output**: one 4-lane DSI at the validated 928.8 Mbps/lane
  carries 148.5 MHz at most (1080p120 needs ~1.7 Gbps/lane).
- **A Lite+ dropped off USB after an 864p144 → 720p100 Video Mode switch** and
  stayed off until power-cycled. Not reproduced or investigated.
- **The scaled 1080p-on-720p path was not re-checked at 100/120 Hz**, and the
  morning's decoder memory exhaustion was not re-run with a live air unit after
  patch 0032 (the close-failure path it fixes was reproduced and verified).
- **When Kestrel dies, DRM's cleanup commit fails** (`atomic remove_fb failed
  with -22`, a kernel warning): the VO atomic check rejects it, and the last
  frame stays on the plane until the next commit.
- **Wave5 warns `Execution of a job in state STOP illegal`** when a session
  ends with work queued (upstream warning, harmless here).
- **The RAM image keeps pairing and settings in RAM**: every reboot loses
  them. The flashable image keeps them in `usr_data`.
- **A card put in after boot is not mounted**: the card is looked for at boot
  only (Format SD Card does mount the card it makes).
