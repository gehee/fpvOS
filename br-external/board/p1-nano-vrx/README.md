# BETAFPV P1 Nano VRX

The P1 HD VRX (Standard or Nano; stock product `P1_GND_VRX`, hardware V2.3,
board `c401`) runs the P1 ground image, `./build.sh p1-gnd` (`board/p1-gnd`):
one kernel and system for the VR04 goggles, the VR04 Pro goggles and this VRX,
with a bundle per unit, `fpvos-p1-gnd-vrx-<version>.fwu`, carrying this
folder's device tree. It is the P1 goggles platform with the panel replaced by
an HDMI output, and the P1 Air's flash layout.

This folder holds what is the VRX's own in that image: its device tree
(`dts/betafpv-p1-nano-vrx.dts`) and its radio settings (`radio.json`, Open8030
profile `betafpv-p1-nano-vrx.c`). Its own image (`p1nanovrx_defconfig`) is gone.

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

The P1 ground image's updater (`fpvos-update` backend `p1-gnd`): fpvOS goes in
the bank stock is not running from, and the stock bank is kept and selectable
from the Flasher (Switch to stock). See `board/p1-gnd`. First installation
needs fpvOS's recovery from RAM: the Flasher's preparation on Linux or
ChromeOS, or the Stock Flasher / Recovery app on macOS and Windows.

## Kestrel

The P1 ground image carries kestrel-gnd's `p1goggle` runtime (the keys are the
goggles' ladder, under the goggles' evdev name `p1-goggle-keys`). Settings and
pairing are kept in stock's `usr_data` volume (`S46kestrel-state`).

## Not done

Boot, HDMI picture, keys, LEDs and installation have now been exercised on
P1 VRX HD and Nano hardware. Nano HDMI needed a temporary forced-1080p60
override when EDID returned no modes; that workaround is not included here.
Live radio reception, SD and persistent-settings regression remain outstanding
for this controls change, as does investigation of the radio's C4 line.

## Keypad and status LED

GPIO97 must stay high to enable the ADC keypad, matching stock `adc.sh`.
Record, Back, Left, Down, Right, Up and Center were verified on the connected
P1 VRX HD with this enable. It has no observed dedicated Bind key.

The VRX status chain uses SPI1 at `0x01102000`, CS0, mode 3, 6.25 MHz. The
`betafpv,p1-vrx-status-led` driver mirrors RGB to the three-entry GRB chain
using stock's eight-SPI-bit encoding. It exposes `/sys/class/leds/fpvos:status`
as a standard multicolor LED. Red, green, blue and off were verified on this
unit. SPI1 defaults disabled in the shared SoC tree. The VRX and goggles
explicitly enable their LED nodes; the goggles Pro does not.

Kestrel's optional status framework requires a runtime built with that feature;
an older pinned runtime will leave the LED off. See Kestrel's
`docs/status-led.md` for patterns and lifecycle. New driver/framework patterns
were tested with temporary modules and then installed and boot-verified on
the P1 VRX HD. Nano video, buttons, Bind and LEDs were also confirmed, and
goggles red LEDs and button operation were confirmed in a RAM test.

The stock application also references PWM8 for a buzzer. The PWM counter runs,
but no sound was observed on the VRX HD. PWM8 tones were audible on the Nano.
Buzzer integration is not included here.
