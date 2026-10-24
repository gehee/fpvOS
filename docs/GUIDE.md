# User guide

How to fly and use fpvOS on the Caddx Ascent VRX Pro. This guide is for release
**2026.10.beta4**. Something not working? [Troubleshooting](TROUBLESHOOTING.md).

- [The controls](#the-controls)
- [The live view](#the-live-view)
- [The menu](#the-menu)
- [Binding an air unit](#binding-an-air-unit)
- [Channel, power and where you fly](#channel-power-and-where-you-fly)
- [DVR and the gallery](#dvr-and-the-gallery)
- [The stats screen](#the-stats-screen)
- [The WiFi spectator view](#the-wifi-spectator-view)
- [Themes](#themes)
- [Settings files](#settings-files)

## The controls

The goggle has seven front buttons: **up, down, left, right, OK, REC and ESC**,
and a separate **BIND** button. fpvOS calls OK *Enter* and ESC *Back*. The four
directions repeat when you hold them.

| | Live view | Menu | Gallery strip | Playback | Stats |
|---|---|---|---|---|---|
| **OK** | open the menu | start changing a setting, then apply it | play | pause, or replay at the end | |
| **ESC** | open the gallery | step back: value, then blade, then close | back to live | back to the strip | back to the strip |
| **Left / Right** | | pick a blade or tab; leave a change pending | browse | seek 5 s | |
| **Up / Down** | | pick a row; change a value | **Down** asks to delete | | change the window |
| **REC** | start or stop recording, from any screen | | | | |
| **BIND** | start a bind, press again to cancel | | | | |

## The live view

With no aircraft the goggle shows the **fpvOS** wordmark and *Ready*. When the
aircraft links up you get the **canopy HUD**: the instrument display, with your
Betaflight OSD over it.

Before the first picture, the *ACQUIRING VIDEO* screen shows where the link is:

| Caption | It means |
|---|---|
| `SEARCHING` | no radio link yet, and no flight controller telemetry |
| `LINK <n> MHz` or `LINK UP` | the radio is linked; the goggle hasn't started the handshake yet |
| `HANDSHAKE` | handshake sent; no flight controller telemetry yet |
| `WAITING FOR KEYFRAME` | linked, but no picture it can decode yet |

In flight:

- The canopy shows **DISARMED**, **ARMED**, or **STANDBY** (the air unit is at
  low power).
- A red **REC m:ss** shows while you record.
- Link warnings: **amber** when the radio rate is being squeezed, **red** when
  the picture is breaking up or no frame has arrived for 400 ms.
- If the link goes quiet for about a second and a half the panels dim and
  **IDLE** appears on the right rail. They come back when the link does.

## The menu

Press **OK** on the live view. The menu opens on two folded **blades**:
**GOGGLE** and **AIR UNIT**.

1. **Left / Right** picks a blade and **OK** unfolds it.
2. **Left / Right** changes tab, **Up / Down** changes row.
3. **OK** on a setting starts changing it. **Up / Down** change the value and
   **OK** applies it.
4. **Left** backs out of a change and leaves it pending, marked `*`: the help
   line reads *Pending: A → B. OK sends it.*
5. **ESC** steps back: the value, then the blade, then the menu closes.

HUD settings and most DISPLAY settings apply as you change them. VIDEO, RADIO,
DVR Source, Background Video, Screen Mode and WiFi AP wait for OK. An action
row (like Bind) runs when you press OK.

### GOGGLE

| Tab | Setting | Values |
|---|---|---|
| **HUD** | HUD Style | OFF · CANOPY · ARENA · ARENA FULL |
| | Betaflight OSD | ON · OFF |
| | Canopy Voltage | PER CELL · PACK (CANOPY only) |
| | Calib Distance | OK zeroes the distance here; Left / Right trim it |
| | Clock | OFF · IDLE ONLY 12H · IDLE ONLY 24H · ON 12H · ON 24H |
| | Dynamic HUD | OFF · SMALL · MEDIUM · EXTREME: how far the HUD moves with the aircraft |
| | Debug Info | OFF · ON: a line of radio details under the right panel, for field tests. While ON, the VRX also keeps its log on the card (`fpvOS_<date>_<time>.log` next to the recordings, newest 30) and a kestrel-air unit keeps a log of each armed flight on its flash (`/usrdata/fpv/air/logs`, newest 5) |
| **DISPLAY** | Theme | KESTREL · EMBER · ICE · MONO · VIOLET |
| | Background Video | ON · OFF |
| | Picture Size | 60% to FULL, in steps of 5 |
| | UI Scaling | 0.5x to 2.0x, in steps of 0.1 |
| | Brightness | 0 to 100, in steps of 5 |
| | ADVANCED › Frame Mode | SPLIT · FULL FRAME (default) · FULL DECODE |
| | ADVANCED › Refresh Sync | OFF · ON · FREE: the screen's refresh follows the camera |
| | ADVANCED › Sync Margin | 0 to 4 ms, only while Refresh Sync is on |
| **DVR** | Source | FPV · SCREEN |
| | Folder, Space Left | read-only |
| **SYSTEM** | Build, Version, Decoder | read-only |
| | Screen Mode | Auto, or a mode your screen offers (`WxH @ N Hz`) |
| | WiFi AP | ON · OFF (see [the spectator view](#the-wifi-spectator-view)) |
| | Where you fly | Amateur Licence, Area, Country and Timezone |

**Frame Mode** is how a picture reaches the screen. **SPLIT** is the lowest
latency: the top half of a picture is shown before its bottom half has arrived,
so a frame can look split. It only helps on high refresh rate displays and
stays off on a 60 Hz one. **FULL FRAME** (the default) waits for the whole
picture. **FULL DECODE** decodes it completely before showing it.

**Refresh Sync** times the screen's refresh to the camera's frames, on the
goggle alone, so each picture meets a refresh instead of waiting for the next
one. **ON** needs a refresh rate that is a whole multiple of the camera's frame
rate; **FREE** also takes a screen running faster than the camera. Its help
line says what it does to your screen in the current video mode. **Sync
Margin** puts the refresh up to 4 ms later: fewer pictures miss their refresh,
for that much latency. Both are worth leaving alone unless you are chasing
latency or smoothness.

**Screen Mode**, **Refresh Sync ON** and **FREE** go on trial: the goggle
applies the setting, then asks *Keep it?*. If you do nothing it goes back after
15 seconds.

### AIR UNIT

| Tab | Setting | Values |
|---|---|---|
| **VIDEO** (only while linked) | Video Mode | 720p60 · 720p100 · 1080p60 · 1080p100, and with an fpvOS air unit whose camera has them 864p120 · 864p144 (1536x864) |
| | Max Bitrate | AUTO · 6 · 8 · 10 · 12 · 15 · 18 · 20 · 22 · 25 · 30 · 35 · 40 Mbps. The air unit goes above 20 Mbps only when the link carries it. With a stock air unit the row is dimmed and reads *FPVOS AIR ONLY*: the stock app ignores the cap |
| | Rotate | 0 · 180 |
| | Scene | Race · Standard |
| | EV | -1.0 to +1.0 |
| | White Balance | Auto, or 4000K to 7000K in steps of 100K |
| | Saturation, Contrast, Sharpness | Auto, or 1 to 10 |
| | 3D DNR | Off · Low · Mid · High · Auto |
| | Focus Mode | On · Off |
| **RADIO** | Bind | only while unlinked |
| | Channel | opens the [channel page](#channel-power-and-where-you-fly) |
| | TX Power | Lite: 25 mW · 100 mW · 100 mW AUTO. Lite+: 25 · 100 · 200 · 500 mW · 500 mW AUTO. It reads `--` until the air unit has said which it is |
| | Max MCS | AUTO · MCS 0 to 11: the highest MCS the goggle's radio may receive at (shown while it runs Open8030) |
| | VRX Radio Firmware | OPEN8030 · STOCK: the firmware on **this goggle's** radio chip, not the air unit's. OK applies it: the radio restarts and the picture is back in about 10 s |
| | Auto Standby | ON · OFF |
| **SERIAL** | Receiving, Frames, Data | read-only: the flight controller's MSP traffic |
| **INFO** | Model, HW Version, SN, SW Version | read-only. With an fpvOS air unit also fpvOS, kestrel-air, Radio Driver, Radio Firmware, Kernel, Camera and its Capabilities (Air Timing, Radio Clock, Frame Clock, Sensor Timing, Intra Refresh, Camera IMU, FC IMU, Bandwidth Cap, 864p120, 864p144: whichever it has) |

Rotate and 3D DNR show what the air unit reports it is really running.

## Binding an air unit

An air unit that was bound to your goggle under stock firmware links without
binding again. A new one needs a bind, with the goggle and the air unit both
powered and close together:

1. On the goggle, open **AIR UNIT › RADIO › Bind** and press **OK**, or press
   the goggle's **BIND** button (it works with the menu closed).
2. On the air unit, **hold its bind button until the LED turns red**. The
   goggle shows *Push the bind button on the air unit*.
3. The goggle counts the bind window down (`BINDING 120s`) and then shows the
   result for a few seconds:

| Shown | It means |
|---|---|
| `BOUND` | done: the air unit is paired and links |
| `ALREADY LINKED` | nothing to do |
| `NO AIR UNIT FOUND` | nothing answered in the 120 s: move closer, check the air unit has power, and try again |

Press the BIND button again to cancel.

## Channel, power and where you fly

**AIR UNIT › RADIO › Channel** opens the channel page. It shows the channels
your country allows.

- **Left / Right** walks the channels. The first slot is **AUTO**.
- **Up** jumps to the quietest allowed channel, **Down** returns to the one the
  link is on.
- **OK** moves the link there at once. **ESC** closes the page.

A channel picked here lasts for the session. **TX Power** is saved per air unit
and starts at 25 mW; the levels offered are the ones that air unit has.

Under **SYSTEM › Where you fly**, set your **Amateur Licence**, **Area** and
**Country** (and **Timezone**, if your country has more than one). The channel
page and the power levels follow your country's rules. They are a help, not a
guarantee: what is legal where you fly is your responsibility.

## DVR and the gallery

**REC** starts and stops recording from any screen. There is no automatic
recording when you arm.

**DVR › Source** chooses what is recorded:

- **SCREEN** (the default) records what you saw: the video **and** the HUD,
  blended and encoded in H.265 at up to 100 fps - every refresh of a 100 Hz
  screen, every other one of a 120 Hz screen. It costs the live picture about
  half a millisecond.
- **FPV** records the air unit's own stream, with no HUD, straight to the file.
  A picture the radio lost is replaced by a copy of the one before, so the file
  plays everywhere, QuickTime included.

Recordings are MP4 files, named `fpvOS_YYYYMMDD_HHMMSS.mp4`, on the card's
**recordings partition** (`/media/dvr`, exFAT, labelled `dvr`). The first boot
creates it, ready to record straight away (if it cannot, the goggle restarts
itself once to finish it).

**The goggle deletes your oldest recordings** (the `fpvOS_` files) before a new
one starts if less than 300 MB is free. Copy flights you want to keep.

### The gallery

Press **ESC** on the live view. The strip runs from your oldest recording to the
newest, then the **LIVE** tile, then the **STATS** tile. Only recordings that
play are listed.

- **Left / Right** browse and **OK** plays.
- In playback, **Left / Right** seek 5 s and **OK** pauses. The title and the
  timeline fade out a few seconds after the last button; any button brings
  them back, and they stay while paused.
- **Down** asks to delete. **CANCEL** is pre-selected: **Right** picks DELETE and
  **OK** confirms.
- **ESC** goes back.

### Getting recordings off

- **Card reader:** power the goggle off, take the card out and put it in your
  computer. The `dvr` partition is exFAT, which Windows, macOS and Linux read.
- **WiFi:** the [spectator view](#the-wifi-spectator-view) lists them with a
  **SAVE** button, so you can download one to a phone.

## The stats screen

The **STATS** tile at the end of the gallery strip shows the flight live, with
the picture small in a corner:

- **LATENCY** under the picture: the median, the 99th percentile and the
  window's worst, glass to glass.
- **SMOOTH**, **SHOWN/DECODED** (frames per second) and **LOST**: how evenly
  pictures arrive, with a band of the spacing between them.
- **BITRATE**, **LINK USE**, **MCS / SNR** and **CHANNEL**: the link, with its
  bandwidth drawn in the link lane.
- **VTX TEMP** and **VRX TEMP**.
- Each slice's life on one timeline, from the camera's exposure to the moment
  it lit the screen, and a table of the stages (**Exp**, **Read**, **Enc**,
  **RF**, **Dec**, **Disp**) with their median and 99th percentile.

**Up / Down** choose the window: 2 s, 5 s, 10 s, 1 minute or 3 minutes. With
the fpvOS air image every stage is measured, the air unit's encoder and radio
included. With a stock air unit the goggle estimates the air side.

## The WiFi spectator view

Switch it on from **SYSTEM › WiFi AP**. It is **off after every boot** and the
setting is not remembered.

- **Plug an external antenna into the goggle's WiFi uFL connector first.** The
  menu warns you.
- It is a **2.4 GHz** transmitter: range-test your control link with it on
  before you fly that way.
- Connect a phone or computer to **`fpvOS-XXXX`** (the last four hex digits of
  the goggle's WiFi MAC). The default password is **`12345678`**; change the name
  and password in `/etc/fpvos/wifi-ap` on the card if other people could be in
  range. Up to four devices can connect. The **WiFi AP** row shows two QR
  codes: one joins the network, the other opens the page.
- Open **<http://192.168.4.1>**. The **LIVE** tab shows what the goggle shows,
  HUD included, re-encoded for the phone at up to 30 frames a second within
  5 Mbit/s. A badge in the corner reads **LIVE**, **CATCHING UP**,
  **RECONNECTING** or **PAUSED**; tap it for the numbers. There is a
  full-screen button, and a phone on its side shows the picture alone.
- The **GALLERY** tab lists your recordings with **PLAY**, **SAVE** and
  **DELETE**, and marks the one being recorded.
- The page also shows the goggle's time zone, with a button to **use your
  phone's**.

The page wears your theme too.

## Themes

A theme in fpvOS is not a tint laid over the HUD. The interface is built on
**colour roles**, every element on screen belongs to one, and a theme is a
palette for those roles:

| Role | What it colours |
|---|---|
| **text** | headline figures and row type |
| **data** | the measured tracks: cell level, link quality |
| **accent** | live state: armed rails, the sag track, VIDEO |
| **ground** | the panels the HUD is cut from |
| **quiet** | state words, track labels, anything qualifying a number |

A theme swaps the hues, never the meaning: a pilot who has learned the layout on
one theme reads every other one the same way. Each palette is checked against
the two backgrounds that actually occur in flight, bright sky and dark ground
in shadow, because everything is drawn over live video of unknown brightness.

| Theme | Character |
|---|---|
| **KESTREL** | The original: cyan instrumentation, lime for live state, a deep blue ground that lifts thin type off bright video |
| **EMBER** | Warm amber readings and a hotter orange for live state |
| **ICE** | Pale blue under a cyan accent: the quietest over bright sky, where lime can glare |
| **MONO** | No colour at all: state carried by brightness alone. The most legible over anything, and the accessible choice |
| **VIOLET** | Cold blue readings against a magenta live state: the widest hue separation, state unmistakable at a glance |

One theme dresses everything: the canopy HUD, the menus, the signal-lock
screen, and the web page, whose live view and DVR gallery pick up the goggle's
theme too. It switches live from **DISPLAY › Theme**, no restart, and is
remembered across boots.

**Want a theme?** Open a
[theme request](https://github.com/gehee/kestrel-gnd/issues/new?template=theme_request.md)
with a preview (a mockup, a screenshot you've recoloured, or just the five
colours) and vote for the ones you'd fly with (👍 on the issue). **The
highest-voted requests get implemented.**

## Settings files

Settings live in `/etc/kestrel/kestrel-gnd.yaml` on the card, as plain
`key: value` lines, and the menu edits them. Deleting the file restores the
defaults on the next boot. The clock and time zone are in
`/etc/kestrel/time.conf`. To get at them, see
[connecting over USB](INSTALL.md#connecting-over-usb-advanced).
