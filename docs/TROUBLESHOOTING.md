# Troubleshooting

Find what you see, then try the fix. This page is for release **2026.10.beta4**.
If it doesn't solve it, [get help](../SUPPORT.md): say what you see, your
versions, and attach the [logs](#collecting-logs).

**The fastest test of all:** pull the SD card. The goggle boots its own stock
firmware, so you can tell a goggle or air unit problem from an fpvOS one.

- [The goggle doesn't show the fpvOS idle screen](#the-goggle-doesnt-show-the-fpvos-idle-screen)
- [No video](#no-video)
- [The video breaks up or freezes](#the-video-breaks-up-or-freezes)
- [The air unit won't bind](#the-air-unit-wont-bind)
- [Recording and the gallery](#recording-and-the-gallery)
- [The menu, the clock and the WiFi view](#the-menu-the-clock-and-the-wifi-view)
- [Flashing the air unit](#flashing-the-air-unit)
- [Known issues](#known-issues)
- [Collecting logs](#collecting-logs)

## The goggle doesn't show the fpvOS idle screen

You see the stock screen, or nothing.

| Check | Fix |
|---|---|
| Is the card in, all the way, before power-on? | Power off, reseat the card, power on. |
| Did Etcher finish and **verify**? | Flash again and wait for *Flash complete* and the verification. A card that fails to verify is bad, or the reader is. Try another card or reader. |
| Did you flash the [`.img.xz`](https://github.com/gehee/fpvOS/releases/latest) itself? | Etcher reads it as is. Don't flash `SHA256SUMS` or the `-licenses` and `-sources` files. |
| Black screen only | The first boot takes a little longer: it sets up the card as it goes. Give it a moment. |

Still nothing? Boot without the card to confirm the goggle itself is fine.

## No video

The goggle is on fpvOS and the air unit is on, but there's no picture. The
*ACQUIRING VIDEO* screen names the step it is stuck on:

| Caption | Likely cause | Try |
|---|---|---|
| `SEARCHING` | no radio link | Is the air unit powered, with antennas on? Is it bound to **this** goggle? Open **AIR UNIT › RADIO**: if it shows a **Bind** row you are not linked, so [bind](#the-air-unit-wont-bind). |
| `LINK <n> MHz` / `LINK UP` | linked, but the handshake hasn't started | Wait a few seconds. Still stuck: power-cycle the air unit. |
| `HANDSHAKE` | the air unit hasn't answered | Wait a few seconds. Still stuck: power-cycle the air unit. |
| `WAITING FOR KEYFRAME` | linked, but no picture the goggle can decode yet | Move closer and check the antennas. Still stuck: power-cycle the air unit. |

**The goggle restarted and the picture hasn't come back:** give it a few
seconds, then power-cycle the air unit.

**Right after flashing the fpvOS air image**, the unit restarts twice. Wait for
it to settle before you judge it.

## The video breaks up or freezes

The HUD tells you which kind of trouble it is: **amber** means the radio is
squeezing the rate, **red** means the picture is breaking up or no frame has
arrived for 400 ms.

- **Antennas:** attached, undamaged, not touching metal or the battery.
- **Channel:** open **AIR UNIT › RADIO › Channel** and press **Up**: it jumps to
  the quietest channel your country allows. **OK** moves the link at once.
- **With an fpvOS air unit:** try a lower **Max Bitrate** (**AIR UNIT ›
  VIDEO**).
- **The top of the picture looks split or torn:** **DISPLAY › ADVANCED › Frame
  Mode** is on **SPLIT**, which shows the top half before the bottom half has
  arrived. Use **FULL FRAME**.
- **Range:** if the HUD shows **IDLE** and the panels dim, the link went quiet.
  They come back when it does.

## The air unit won't bind

1. Put the goggle and the air unit close together, both powered.
2. **AIR UNIT › RADIO › Bind** (or the goggle's **BIND** button), then **hold the
   air unit's bind button until its LED turns red**.
3. You have 120 seconds. `BOUND` means it worked.

`NO AIR UNIT FOUND`: nothing answered. Check the air unit's power, move closer
and retry. `ALREADY LINKED`: nothing to do.

An air unit bound to this goggle under stock firmware doesn't need a bind. If it
won't link anyway, bind it again from the menu.

## Recording and the gallery

| What you see | Cause and fix |
|---|---|
| REC does nothing, no red **REC** counter | The recordings partition isn't there. The first boot creates it, and may restart the goggle once to do so: **power the goggle off and on**. If it still doesn't record, flash the card again. The log says *not a mounted recordings partition*. |
| A recording is gone | The goggle deletes the oldest `fpvOS_` recordings before a new one starts when less than 300 MB is free. Copy what you want to keep. |
| The gallery is empty or missing a flight | It lists only recordings that play. A recording cut short, by a power loss for example, may not. |
| Recordings have no HUD | **DVR › Source** is on **FPV**, which records the air unit's stream as it is. Use **SCREEN** for video and HUD. |
| The card is full | Delete from the gallery (**Down** on a clip), or copy them to a computer first. See [DVR and the gallery](GUIDE.md#dvr-and-the-gallery). |

## The menu, the clock and the WiFi view

| What you see | Cause and fix |
|---|---|
| No **VIDEO** tab | It shows only while an air unit is linked. |
| **Max Bitrate** is dimmed and reads *FPVOS AIR ONLY* | The cap is a command the fpvOS air image understands; a stock air unit ignores it. |
| The clock is wrong | It shows UTC until you set your location: **SYSTEM › Where you fly** (Country and Timezone), or open the WiFi view and press **use this phone's** time zone. |
| The WiFi network isn't there | **SYSTEM › WiFi AP** is off after every boot, and the setting isn't remembered. Switch it on, with the external antenna plugged in. |
| Can't open the page | Connect to `fpvOS-XXXX` (password `12345678` unless you changed it) and open `http://192.168.4.1`. |
| A setting went somewhere strange | Delete `/etc/kestrel/kestrel-gnd.yaml` to get the defaults back (see [Settings files](GUIDE.md#settings-files)), or flash the card again. |
| A new **Screen Mode** gives a blank screen | Wait 15 seconds: it goes back by itself unless you press **OK** to keep it. |

## Flashing the air unit

| What you see | Fix |
|---|---|
| The flasher page says it can't work | Use **Chrome or Edge on a desktop computer**. Web Serial isn't in other browsers or on phones. |
| The port list is empty, or **Connect** fails | Close the Caddx PC tool and any serial terminal: only one program can open the port. On Linux, add your user to the `dialout` group. Try another cable or port. |
| The page rejects the file | Don't rename it: its name has to end in `Ascent_H_Sky_18_21_10.img`, as downloaded. Download it again from the [release assets](https://github.com/gehee/fpvOS/releases/latest). |
| The flash stopped half way | Keep it powered and flash again. If the unit no longer shows up, ask on [Discord](https://discord.gg/CXhNKYFF2v) before trying anything else. |
| I want stock back | [Flash Caddx's update](INSTALL.md#going-back-to-stock). |

## Known issues

fpvOS is a beta. Fly it, but keep a stock card handy.

- The **Lite+ has no 1080p mode above 100 fps**: its fast modes are 864p120
  and 864p144 (1536x864).
- **Early presentation** (the top half first, **SPLIT**) only helps on high
  refresh rate displays. On 60 Hz it stays off.
- **Small, occasional video artifacts** have been seen in test flights.
- **Blocky patches and tears with a stock radio on the air unit**: with the
  goggle's radio on Open8030 (the default) and the air unit's radio on
  Artosyn's firmware (a stock air unit), parts of pictures arrive damaged or
  not at all, more so as the link changes rate. With Open8030 on both ends, or
  Artosyn's firmware on both, the picture is clean. Until it is fixed: flash
  the fpvOS air image, or set **RADIO › VRX Radio Firmware** to **STOCK**.
- **Constant artifacts that don't clear**: once, after a screen was plugged
  into the goggle while it was running, the goggle's radio started delivering
  parts of the video twice. Changing channel, changing the screen mode or
  restarting the app did not clear it. **Power-cycle the goggle** to fix it. The
  cause isn't known yet.
- The goggle has no in-app **diagnostics export** yet: [logs](#collecting-logs)
  are collected over USB.

The notes of each [release](https://github.com/gehee/fpvOS/releases) list what
changed and what is still known.

## Collecting logs

A good report has the logs. They live in the goggle's memory, so **they are gone
once you power it off**. Collect them after the problem, before you shut down.

To keep them across a power-off, turn **HUD › Debug Info** on before you fly.
The goggle then also writes its log to the card, next to the recordings
(`fpvOS_<date>_<time>.log`, the newest 30), and an fpvOS air unit keeps a log
of each armed flight, from 10 s before arming to 10 s after disarming, in
`/usrdata/fpv/air/logs` (the newest 5).

Connect the goggle to a computer over USB (see
[connecting over USB](INSTALL.md#connecting-over-usb-advanced)), then:

```sh
ssh root@192.168.3.1 'cat /var/log/kestrel-gnd.log'  > kestrel-gnd.log     # the app, this run
ssh root@192.168.3.1 'cat /var/log/ar8030-boot.log'  > ar8030-boot.log     # the radio's start-up
ssh root@192.168.3.1 'cat /var/log/ar8030-chip.log'  > ar8030-chip.log     # the radio chip's own log
```

(The password is `fpvos`. Use `cat`, as here: the goggle has no `scp`/sftp
server.) `kestrel-gnd.log.prev` is the run before this one.

Add your versions: **SYSTEM › Version** on the goggle, and **AIR UNIT › INFO**
for the air unit. For the OSD or telemetry, add the flight controller and its
firmware.

**Don't post `/factory/user_cfg.json`.** It lists the air units your goggle is
paired with.
