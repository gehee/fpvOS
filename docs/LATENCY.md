# Latency

Glass-to-glass latency of fpvOS **2026.10.beta4**: a Caddx Ascent Lite+ running
the fpvOS air image, a VRX Pro running the fpvOS goggle image, measured from a
light in front of the camera to the moment the screen shows it. What each
display setting costs, and how smooth it looks.

## In short

| Video mode | Lowest latency | Smoothest | Default settings |
|---|---|---|---|
| **864p120** (12 Mbps) | **24.6 ms**, mostly smooth | 27.5 ms, very smooth | 29.8 ms, smooth |
| **720p100** (12 Mbps) | **25.9 ms**, mostly smooth | 30.3 ms, very smooth² | 31.3 ms, judders |
| **1080p100** (20 Mbps) | **30.0 ms**, smooth | 35.2 ms, smooth | 36.8 ms, judders |
| **864p144** (12 Mbps) | 28.8 ms, judders | no smooth setting on a 120 Hz screen | 29.6 ms, judders |

- **Lowest latency:** Frame Mode **SPLIT** with Refresh Sync **FREE**. The
  latency here is when the top of the picture lights up. The bottom half lands
  8 to 10 ms later, so fast motion shows a tear between the two halves. Without
  tearing, the fastest is 864p120 with FULL FRAME + FREE at 29.1 ms, or 27.5 ms
  with whole pictures timed to the last slice (see below).
- **Smoothest:** Frame Mode **SPLIT** with Refresh Sync **FREE** and
  `display_lock_slice: 2` in the settings file, which times the screen to whole
  pictures, plus **Sync Margin 2 ms**. In the menu alone, **FULL FRAME** +
  **FREE** comes close.
- **Default settings:** FULL FRAME with Refresh Sync OFF.
- **On a 120 Hz screen, fly 864p120.** Camera and screen run at the same rate,
  so it is the fastest mode and the smoothest.
- **Refresh Sync FREE is the setting that matters.** It stretches each refresh
  so the screen runs exactly at the camera's rate. That makes 100 fps smooth on
  a 120 Hz screen and lowers latency in every mode where the camera is not
  faster than the screen.
- **Refresh Sync ON does not help on this screen.** It needs a refresh that is
  a whole multiple of the camera's rate.
- **Sync Margin 2 ms makes whole pictures very smooth.** Sync Margin
  (DISPLAY › ADVANCED, 0 to 4 ms) shows each picture that much later, so fewer
  miss their refresh. With whole pictures, 2 ms took out most of the hitches
  for about 2 ms of latency. With SPLIT it took out few: the top half arrives
  too unevenly for 2 ms to cover. See [Sync Margin](#sync-margin) below. The
  main tables were measured at 0.
- **FULL DECODE is never better than FULL FRAME.**
- **864p144 needs a 144 Hz screen.** On a 120 Hz screen about one picture in
  six is never shown, whatever the settings.

Settings are in the menu under **DISPLAY › ADVANCED** (see the
[user guide](GUIDE.md#the-menu)). The video mode and bitrate cap are under
**AIR UNIT › VIDEO**.

## Smoothness

Smoothness is how evenly the pictures reach the screen. It is the **SMOOTH**
figure on the [stats screen](GUIDE.md#the-stats-screen): the share of pictures
shown exactly one camera frame after the one before. The words in these tables
mean:

| Word | What you see | Pictures on time |
|---|---|---|
| **Very smooth** | Even motion. | 95% or more |
| **Smooth** | An occasional hitch: one picture in 10 to 20 shown a refresh late. | 90 to 95% |
| **Mostly smooth** | A hitch about every 7 to 10 pictures. | 85 to 90% |
| **Judders** | Camera and screen run at different rates. At 100 fps on 120 Hz, pictures alternate between one and two refreshes on screen. At 144 fps on 120 Hz, one picture in six is dropped. | The stats screen reads 0% |

## How it was measured

- **Rig:** an LED in front of the air unit's camera, and a photodiode on the
  goggle's screen, both driven by an ESP32-S3. Each reading is the time from
  the LED turning on to the screen getting brighter. That is about 100 readings
  per setting, over 75 seconds.
- **Equipment:**

  | | |
  |---|---|
  | Air unit | Ascent Lite+ (OS02K10 sensor), fpvOS 2026.10.beta4 air image, Open8030 radio firmware |
  | Goggle | VRX Pro, fpvOS 2026.10.beta4 goggle image (Open8030 `ed20c01`) |
  | Screen | A 1920x1080 HDMI headset panel at 120 Hz (60 and 120 Hz modes only, no FreeSync) |
  | Link | Channel 5914 MHz, 20 MHz wide, MCS 11, short radio frame, on the bench |

- **Each setting was a fresh start** of the goggle app with that setting. There
  were 20 seconds to settle before measuring.
- **Run-to-run noise** is about ±1 to 2 ms on the median. Differences smaller
  than that are not real.
- **What is included:** the camera's own frame time, so on average half a
  frame of waiting before the LED is even captured. It also includes the
  screen's own delay between receiving a picture and lighting it. A faster
  screen lowers every number here.
- **Capture → lit** is the goggle's own figure, from the camera capturing the
  row to the screen showing it, on the radio's shared clock. It leaves out the
  camera's frame wait and the panel's delay. For SPLIT it is given for the top
  and the bottom of the picture.
- The tables give the **median** and the **10th–90th percentile** spread of the
  photodiode readings.

## All results

### 864p120, 12 Mbps

| Frame Mode | Refresh Sync | Glass to glass (p10–p90) | Smoothness | Capture → lit (top / bottom) | Screen refresh |
|---|---|---|---|---|---|
| SPLIT | FREE | **24.6 ms** (21.9–28.0) | mostly smooth | 16.0 / 24.4 ms | 119.98 Hz |
| SPLIT | ON | 26.8 ms (22.1–31.5) | mostly smooth | 18.5 / 23.5 ms | 120.09 Hz |
| SPLIT | FREE, whole pictures¹ | 27.5 ms (25.2–30.5) | **very smooth** | 19.6 ms | 119.98 Hz |
| FULL FRAME | FREE | 29.1 ms (25.7–31.0) | smooth | 19.9 ms | 119.98 Hz |
| SPLIT | OFF | 29.2 ms (25.1–33.7) | smooth | 21.1 ms | 120.19 Hz |
| FULL DECODE | FREE | 29.3 ms (26.6–32.6) | mostly smooth | 21.1 ms | 119.98 Hz |
| FULL FRAME | OFF *(default)* | 29.8 ms (26.0–34.5) | smooth | 21.3 ms | 120.19 Hz |
| FULL FRAME | ON | 30.4 ms (25.6–34.7) | smooth | 21.9 ms | 120.09 Hz |
| FULL DECODE | OFF | 31.9 ms (27.4–36.6) | mostly smooth | 22.8 ms | 120.19 Hz |

### 720p100, 12 Mbps

| Frame Mode | Refresh Sync | Glass to glass (p10–p90) | Smoothness | Capture → lit (top / bottom) | Screen refresh |
|---|---|---|---|---|---|
| SPLIT | FREE | **25.9 ms** (22.4–29.6) | mostly smooth | 16.3 / 26.1 ms | 100.15 Hz |
| SPLIT | ON | 28.1 ms (23.0–33.7) | judders | 18.5 / 21.6 ms | 120.19 Hz |
| SPLIT | OFF | 28.4 ms (23.1–33.4) | judders | 18.5 / 21.6 ms | 120.19 Hz |
| FULL DECODE | FREE | 29.3 ms (26.2–34.0) | mostly smooth | 20.6 ms | 100.15 Hz |
| FULL FRAME | FREE | 29.6 ms (25.1–33.5) | **smooth** | 19.8 ms | 100.15 Hz |
| SPLIT | FREE, whole pictures¹ | 30.0 ms (26.0–33.2) | **smooth** | 19.8 ms | 100.15 Hz |
| FULL FRAME | OFF *(default)* | 31.3 ms (26.1–36.1) | judders | 21.8 ms | 120.19 Hz |
| FULL FRAME | ON | 31.4 ms (26.8–36.8) | judders | 21.9 ms | 120.19 Hz |
| FULL DECODE | OFF | 32.1 ms (27.4–37.0) | judders | 22.7 ms | 120.19 Hz |

### 1080p100, 20 Mbps

| Frame Mode | Refresh Sync | Glass to glass (p10–p90) | Smoothness | Capture → lit (top / bottom) | Screen refresh |
|---|---|---|---|---|---|
| SPLIT | FREE | **30.0 ms** (25.9–33.5) | smooth | 20.4 / 30.2 ms | 100.15 Hz |
| SPLIT | OFF | 33.0 ms (27.2–38.2) | judders | 22.8 / 26.8 ms | 120.19 Hz |
| SPLIT | ON | 33.0 ms (27.5–38.0) | judders | 22.9 / 27.0 ms | 120.19 Hz |
| FULL FRAME | FREE | 35.2 ms (31.3–38.4) | smooth | 25.3 ms | 100.15 Hz |
| SPLIT | FREE, whole pictures¹ | 35.2 ms (31.3–38.5) | **smooth** (the most even) | 25.4 ms | 100.15 Hz |
| FULL DECODE | FREE | 36.0 ms (32.3–39.8) | smooth | 26.7 ms | 100.15 Hz |
| FULL FRAME | ON | 36.3 ms (31.2–42.4) | judders | 27.6 ms | 120.19 Hz |
| FULL FRAME | OFF *(default)* | 36.8 ms (31.6–42.1) | judders | 27.6 ms | 120.19 Hz |
| FULL DECODE | OFF | 37.7 ms (32.6–42.5) | judders | 29.0 ms | 120.19 Hz |

### 864p144, 12 Mbps, on a 120 Hz screen

The camera is faster than the screen, so Refresh Sync never changes the
refresh (it can only slow a refresh down). Every setting judders, and every
setting lands within noise of the others.

| Frame Mode | Refresh Sync | Glass to glass (p10–p90) | Capture → lit (top / bottom) |
|---|---|---|---|
| SPLIT | FREE, whole pictures¹ | 28.8 ms (24.8–32.6) | 20.6 / 21.3 ms |
| SPLIT | FREE | 28.9 ms (24.4–32.8) | 20.7 / 21.4 ms |
| FULL FRAME | ON | 29.1 ms (25.6–33.7) | 20.7 / 21.4 ms |
| SPLIT | OFF | 29.2 ms (25.0–33.7) | 20.6 / 21.3 ms |
| SPLIT | ON | 29.4 ms (24.8–34.5) | 20.8 / 21.5 ms |
| FULL FRAME | FREE | 29.4 ms (24.5–33.5) | 20.7 / 21.4 ms |
| FULL FRAME | OFF *(default)* | 29.6 ms (25.6–33.1) | 20.6 / 21.3 ms |
| FULL DECODE | OFF | 29.9 ms (26.4–35.7) | 21.9 / 22.6 ms |
| FULL DECODE | FREE | 30.0 ms (26.0–34.2) | 21.8 / 22.5 ms |

² *With Sync Margin 2 ms*, see [Sync Margin](#sync-margin).

¹ *Whole pictures:* `display_lock_slice: 2` in `/etc/kestrel/kestrel-gnd.yaml`
on the goggle. Refresh Sync then times the screen to a picture's last slice and
shows it whole, instead of showing its top half early. It has no menu row.

### Sync Margin

Measured at 720p100, 12 Mbps, Refresh Sync FREE, one run each.

| Frame Mode | Sync Margin | Glass to glass (p10–p90) | Smoothness | Pictures a refresh late | Capture → lit (top / bottom) |
|---|---|---|---|---|---|
| SPLIT, whole pictures¹ | 0 | 29.8 ms (25.4–32.3) | smooth | 6.6% | 19.8 ms |
| SPLIT, whole pictures¹ | **2 ms** | 30.3 ms (27.7–34.8) | **very smooth** | **1.0%** | 21.8 ms |
| SPLIT | 0 | 24.9 ms (22.4–33.6) | mostly smooth | 11.5% | 16.3 / 26.1 ms |
| SPLIT | 2 ms | 27.6 ms (24.5–32.1) | smooth | 9.6% | 18.4 / 28.1 ms |

The capture → lit figures move by exactly the margin. The glass-to-glass
difference for whole pictures (0.5 ms) is within the run-to-run noise.
