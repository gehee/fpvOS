# BETAFPV P1 Nano VRX

The `p1-nano-vrx` profile is a first, **untested** fpvOS image for the BETAFPV
P1 Nano VRX (stock product `P1_GND_VRX`, hardware V2.3, board `c401`). It builds;
it has not been booted on a unit. It is the P1 goggles platform with the panel
replaced by an HDMI output, and the P1 Air's flash layout.

```sh
./build.sh p1-nano-vrx config
KESTREL_NATIVE_IMAGE="$P1_RUNTIME_SQUASHFS" ./build.sh p1-nano-vrx all
```

Artifacts are in `output/p1-nano-vrx/images/`: `Image`,
`betafpv-p1-nano-vrx.dtb`, `rootfs.cpio.gz`, the guarded `kernel.img`, and
`fpvos-p1-nano-vrx.fwu` (board `P1NV`, 0x50314e56).

Until the radio profile `betafpv-p1-nano-vrx.c` is in the pinned Open8030
revision, point the build at a checkout that has it, in
`output/p1-nano-vrx/local.mk`:

```make
OPEN8030_OVERRIDE_SRCDIR = /path/to/Open8030
```

## What the board is

Read from one unit on stock 2.0.8 (device tree, startup scripts, logs):

| Part | Wiring | Source |
| --- | --- | --- |
| DRAM | 256 MiB, Linux 148 MiB (`mem=148m`), 107 MiB codec pool | stock command line |
| Radio | AR8030 on SDIO (`mmc0`), reset GPIO23 | `rst_ar813x.sh` |
| SD card | `mmc1`, I/O rail GPIO100 high | stock device tree |
| Keys | ADC ladder on channel 0: bind 200 mV, back 400, record 600, up 800, left 1000, right 1200, enter 1400, down 1600 | stock device tree; the goggles' ladder |
| HDMI | Lontium LT9611EX on I2C0 0x41, interrupt GPIO94 | stock log, I2C scan |
| HDMI reset | GPIO96 | **inferred**: stock exports 94 and 96 when it starts the bridge, and the bridge library uses two lines |
| Decoder | Wave521C, firmware SHA-256 `308b9635...` | identical to the goggles' file, so the `P1_GOGGLE_1_0_36` firmware profile is used |
| Flash | P1 A/B layout, both banks stock 2.0.8, bank 1 running, GPT record in `gpt1` | NAND dump |

Stock also leaves GPIO42 and GPIO107 driven low; the device tree holds them the
same way without knowing their function here.

USB Ethernet is `192.168.3.105/24`, SSH `root:root`. The unit enumerates as
"P1 Nano VRX - fpvOS" by BETAFPV, serial `fpvos-p1-nano-vrx`.

## HDMI bridge

The LT9611EX is not register-compatible with the LT9611 of the Ascent VRX and
the SteadyDigital, nor with the LT9611UXC. It runs its own firmware, which
follows the DSI input and reads the screen's EDID by itself. Kernel patch
`0043-drm-bridge-lontium-lt9611ex.patch` adds a small driver for it: reset,
hot-plug state, EDID, output on and off, over a five-byte command mailbox.
Hot-plug is polled because the SoC GPIO driver has no interrupts yet.

The status commands (`RH1:`, `RH2:`, `RM1:`, `RM2:`) were sent to the unit
under stock and answered as the driver expects. Not checked: a picture. The
VO and DSI use the `ascent-hdmi` profile (CEA 1080p60 on four 928.8 Mbps
lanes, the rate stock's 1080p60 table gives); the DSI video mode stock uses
(burst or sync events) is not known, and the driver asks for the non-burst
mode the Ascent output was validated with.

## Radio

Open8030 profile `betafpv-p1-nano-vrx.c`, DEV over SDIO, with early pins,
explicit I/O domains and optional radio-local factory storage, as the goggles.
The pin list comes from the unit's stock radio image (board type 4, one TX
chain). Open items:

- stock drives the radio's pin C4 low as an output; nothing does that here;
- `radio.json` is the goggles' file: Open8030 accepts only the fpvOS link
  settings (`2TX_STBC`), while stock configures this board as `1TX`.

`/factory/ar8030_pwr.json` exists on the unit and is merged at start as on the
goggles.

## Flash and updates

The updater backend `p1-nano-vrx` is the shared P1 backend, as on the P1 Air:
fpvOS goes in the bank already holding fpvOS, else the bank stock is not
running from; the other bank and whichever env/U-Boot pair the unit uses are
left alone. Both banks hold stock when the unit ships, so installing fpvOS
removes only the copy that is not running.

First installation needs fpvOS's recovery running from RAM; there is no entry
from stock (`P1_STOCK_BOOTSTRAP 0`), and none has been tried on stock 2.0.8.
After that:

```sh
tools/fpvos-update/client.py --board p1-nano-vrx --port <port> info
tools/fpvos-update/client.py --board p1-nano-vrx --port <port> clean
tools/fpvos-update/client.py --board p1-nano-vrx --port <port> install output/p1-nano-vrx/images/fpvos-p1-nano-vrx.fwu
```

`stock` selects the preserved stock bank without rewriting it. Keep a NAND
backup before the first write.

## Kestrel

Build Kestrel Ground with `KESTREL_HAL=ar9311` and `KESTREL_BOARD=p1goggle`
(the keys are the goggles' ladder, under the goggles' evdev name `p1-goggle-keys`),
package it with `tools/package_ascent.py` and pass the runtime as
`KESTREL_NATIVE_IMAGE`. Settings and pairing are in RAM, as on the goggles.

## Not done

Nothing has run on the hardware: boot, HDMI picture, keys, radio link, SD,
install and recovery are all untested. Persistent settings, a first-install
path from stock 2.0.8 and the radio's C4 line are open.

## Keypad and status LED

GPIO97 must stay high to enable the ADC keypad, matching stock `adc.sh`.
Record, Back, Left, Down, Right, Up and Center were verified on the connected
P1 VRX HD with this enable. It has no observed dedicated Bind key.

The VRX status chain uses SPI1 at `0x01102000`, CS0, mode 3, 6.25 MHz. The
`betafpv,p1-vrx-status-led` driver mirrors RGB to the three-entry GRB chain
using stock's eight-SPI-bit encoding. It exposes `/sys/class/leds/fpvos:status`
as a standard multicolor LED. Red, green, blue and off were verified on this
unit. SPI1 defaults disabled in the shared SoC tree and is enabled only here;
the unified P1 build includes the driver but goggles do not instantiate it.

Kestrel's optional status framework requires a runtime built with that feature;
an older pinned runtime will leave the LED off. See Kestrel's
`docs/status-led.md` for patterns and lifecycle. New driver/framework patterns
were tested with temporary modules and then installed and boot-verified on
the P1 VRX HD. Separate Nano VRX hardware has not been tested.

The stock application also references PWM8 for a buzzer. The PWM counter runs,
but no sound was observed on this unit. Buzzer support is not enabled here.
