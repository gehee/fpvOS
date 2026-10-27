# FAQ

**Will it brick my goggle?**
No. The VRX Pro boots from the SD card and fpvOS never writes to the goggle's
own memory. Pull the card and it boots stock. The one step that writes to
hardware is the optional air unit flash, and flashing Caddx's own update the
same way puts the stock firmware back.

**What about my warranty?**
That is Caddx's call, not ours. The goggle itself is never modified: with the
card out it is exactly as it shipped.

**Do I need the fpvOS air image?**
No. A stock Ascent air unit links to fpvOS right away. The air image adds the
steady latency (intra refresh instead of keyframe bursts), the end-to-end
measurements, the HUD that moves with the aircraft and flight controller
telemetry. See [what it adds](#what-the-fpvos-air-image-adds).

**Does it work with my goggles, or my DJI, Walksnail or HDZero gear?**
Today fpvOS runs on the Caddx Ascent VRX Pro, with the Ascent Lite and Lite+ air
units. Other vendors' AR8030 air units use their own link setup and don't pair
with this stack. If you have other AR8030-class hardware,
[come talk to us](https://discord.gg/CXhNKYFF2v).

**Does it work with my flight controller and OSD?**
It draws the Betaflight OSD, and with the fpvOS air image it reads battery,
altitude, GPS and flight modes from the flight controller over MSP.

**Can I trust it to fly?**
It is beta. People fly it, and it is built to be fallen back from: keep a stock
card handy, bench-test first and fly line-of-sight until you trust it on your
setup. [Before you fly](../README.md#before-you-fly).

**What happens when I update?**
A new release is a new image: you flash it to the card again. That erases the
card, recordings and settings included, so copy your flights off first. The
[install guide](INSTALL.md#updating) has the details.

**Is it legal?**
The software is free (GPLv3). Radio rules are yours to follow: kestrel can
change transmit power, channel and bandwidth, and what is legal depends on
where you fly. The channel page follows your country's rules, but it is a help,
not a guarantee.

**Something broke. Who helps?**
The community, on a best-effort basis: [Troubleshooting](TROUBLESHOOTING.md)
first, then [Discord](https://discord.gg/CXhNKYFF2v).

## What the fpvOS air image adds

| | Stock air unit | fpvOS air unit |
|---|---|---|
| Video, binding, channels, power, link stats | ✅ | ✅ |
| Camera settings (EV, white balance, 3D DNR, rotation, video modes) | ✅ | ✅ |
| Canopy HUD, Betaflight OSD, themes, DVR, gallery, WiFi AP | ✅ | ✅ |
| Pictures decoded as their slices arrive | ✅ | ✅ |
| Latency on the HUD | estimated for the air side | measured end to end, capture to screen, by the radio's clock |
| Stats screen | goggle-side stages | every stage, the air unit's encoder and radio included |
| Steady latency: intra refresh instead of keyframe bursts | — | ✅ |
| Reactive HUD | — | ✅ from the camera's IMU (Lite) or the flight controller's gyro (Lite+) |
| Flight controller telemetry (battery, altitude, GPS, flight modes) polled over MSP | — | ✅ |
| A cap on the video bitrate (VIDEO › Max Bitrate, up to 40 Mbps) | — | ✅ |
| AIR UNIT › INFO: what the air unit runs and can do | stock's device info | ✅ with the fpvOS version and its capabilities |
| Recovers by itself from a radio chip reset | as stock | ✅ (restarts) |
| SSH into the air unit over USB (`root` / `root`) | — | ✅ |

The fpvOS air firmware is flashed like a Caddx update, with the Caddx PC tool
or the [fpvOS Flasher](https://gehee.github.io/fpvOS_flasher/), and flashing
the stock update brings the unit back.
