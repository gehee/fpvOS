# Hardware

What fpvOS does on each device it runs on, and each device's specs. Where each
device stands, released or in development, and how it installs is in the
[README](../README.md#hardware-support).

## Features

✅ works on that device · ❌ not yet · — not on that device · ? not checked yet

**Air units**

| Feature | Ascent Lite | Ascent Lite+ | P1 Air |
|---|---|---|---|
| Video to an fpvOS receiver | ✅ | ✅ | ✅ 1080p60, 720p90 |
| Steady latency: intra refresh instead of keyframe bursts | ✅ | ✅ | ✅ |
| Latency measured end to end, capture to screen | ✅ | ✅ | ? |
| Camera settings (EV, white balance, 3D DNR, rotation, video modes) | ✅ | ✅ | ? |
| Reactive HUD | ✅ camera IMU | ✅ flight controller gyro | ? flight controller gyro |
| Flight controller telemetry over MSP (battery, altitude, GPS, modes) | ✅ | ✅ | ? |
| A cap on the video bitrate | ✅ | ✅ | ? |
| USB network (CDC-NCM) and SSH | ✅ | ✅ | ✅ |
| Back to stock | ✅ Caddx's own update | ✅ Caddx's own update | ✅ stock kept in bank 1 |

**Receivers and goggles**

| Feature | Ascent VRX Pro | Ascent VRX | P1 goggles | SteadyDigital |
|---|---|---|---|---|
| Kestrel UI, menus driven by the keys | ✅ | ✅ HDMI | ✅ internal panel | ✅ HDMI, front keys |
| Live video, decoded as its slices arrive | ✅ from an Ascent air unit or a P1 Air | ? | ✅ from a P1 Air | ✅ from an Ascent air unit |
| Canopy HUD, Betaflight OSD, five themes | ✅ | ? | ? | ? |
| Stats screen: latency per stage, link, temperatures | ✅ | ? | ? | ? |
| DVR to the SD card | ✅ FPV and SCREEN | ? | ✅ received video | ✅ |
| Gallery: play, seek, delete | ✅ | ? | ? | ? |
| WiFi spectator view for phones | ✅ | — | — | — |
| Settings and pairing kept across boots | ✅ | ? | ❌ | ? |
| USB network and SSH | ✅ CDC-NCM | ✅ | ✅ | ✅ |
| Update from fpvOS | ✅ write a new card | ✅ self-update | ❌ not qualified | ✅ `tools/fpvos-update` |
| Back to stock | ✅ pull the card | ✅ restore checked | ✅ stock kept in bank 0 | ✅ stock kept in bank A |

## Specs

Every device uses an Artosyn AR8030 baseband for the radio. The decode times
below are what fpvOS measured on the bench, not the vendor's figures.

**Air units**

| Brand | Device | SoC, CPU | RAM | Sensor | Encoder | Video modes | IMU | Radio link |
|---|---|---|---|---|---|---|---|---|
| Caddx | **Ascent Lite** | HiSilicon Hi3516CV610, 2× Cortex-A7 | 128 MiB (64 Linux, 64 media) | CV2004 | H.265, sent slice by slice, intra refresh | 720p and 1080p up to 100 fps, 864p120 | camera IMU | SDIO |
| Caddx | **Ascent Lite+** | HiSilicon Hi3516CV610, 2× Cortex-A7 | 128 MiB (64 Linux, 64 media) | OS02K10 | H.265, sent slice by slice, intra refresh | 720p and 1080p up to 100 fps, 864p120, 864p144 | — | SDIO |
| BetaFPV | **P1 Air** | Artosyn AR9311, 2× Cortex-A53 | 256 MiB | SC231AI | Wave5 HEVC, 4 slices a picture, intra refresh | 1080p60, 720p90 | — | SDIO |

**Receivers and goggles**

| Brand | Device | SoC, CPU | RAM | fpvOS kernel | Decoder | Decode time | Video out | Radio link |
|---|---|---|---|---|---|---|---|---|
| Caddx | **Ascent VRX Pro** | Rockchip RK3568, 4× Cortex-A55 | 1 GiB | Linux 6.12.69 (Rockchip `develop-6.12`) | rkvdec2, H.264/H.265, decodes each slice as it lands | **2.0 ms** from the last slice to the frame (5.1 ms for a whole picture), 1080p100 | HDMI, up to 1080p120 | USB |
| Caddx | **Ascent VRX** (Gnd485) | Artosyn AR9311, 2× Cortex-A53 | 512 MiB (256 Linux, 256 codec) | Linux 6.18.36 | Wave5, H.264/H.265 | not measured yet | HDMI (Lontium LT9511): 720p50–120, 1080p50/60 | SDIO |
| BetaFPV | **P1 goggles** | Artosyn AR9311, 2× Cortex-A53 | 256 MiB (148 Linux, 108 reserved) | Linux 6.18.36 | Wave5, H.264/H.265 | 1080p60 played at 59.9 fps, no late frames (time per picture not measured yet) | internal 1920×1080 panel, 60 Hz | SDIO |
| Skyzone | **SteadyDigital** | Artosyn AR9311, 2× Cortex-A53 | 256 MiB (148 Linux, the rest media) | Linux 6.18.36 | Wave5, H.264/H.265, strips decoded in place | **~3.6 ms** a strip (P1 Air at 2 strips); two 1920×592 decoders at 147 pictures/s together | HDMI (LT9611): 720p60 (720p120 corrupts scaled pictures), 1080p60 at most | SDIO |

The Ascent air image keeps the stock kernel and its memory split: `mem=64m` for
Linux, and the media pool (MMZ) above it from `0x44000000`. The P1 Air runs
fpvOS's Linux 6.18. End to end, a P1 Air into a VRX Pro lights row 0 of the
picture **33.5 ms** after capture (encode 19, radio 5.1, decode 1.0, display
7.8 ms), and 32.0 ms when the VRX Pro decodes it in 4 strips.
