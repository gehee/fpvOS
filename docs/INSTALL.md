# Installing fpvOS

Installing fpvOS on the Caddx Ascent VRX Pro takes three things: a microSD card,
a few minutes, and a computer. You don't open the goggle and you don't flash it.

fpvOS boots the goggle **from the SD card** and leaves its internal firmware
untouched. Pull the card and the goggle boots stock again, so trying fpvOS is
fully reversible.

| Part | What it is | Required? | Time |
|---|---|---|---|
| [1. The goggle](#1-flash-the-card) | write an image to a microSD card, put it in the VRX Pro | yes | mostly Etcher writing the card |
| [2. The air unit](#flash-the-air-unit-optional) | flash the fpvOS air image from your browser | no | a few minutes |
| [3. First flight](#first-flight) | bench check, then fly | | |

You don't need part 2 to fly. Start with the card, fly it with your stock air
unit, and add the air image whenever you're curious.

**You need:** a Caddx Ascent VRX Pro, a microSD card of 2 GB or more, a computer
with a card reader, and [balenaEtcher](https://etcher.balena.io/) (free, for
Windows, macOS and Linux). For part 2 also an Ascent Lite or Lite+ air unit,
its USB cable, and Chrome or Edge on a desktop computer.

## 1. Flash the card

### Get the image

Download [`fpvOS-vrxpro-<version>.img.xz`](https://github.com/gehee/fpvOS/releases/latest) from the
assets of the [latest release](https://github.com/gehee/fpvOS/releases/latest). The same
assets include `SHA256SUMS` if you want to check the download, and the licences
and sources that go with every image. Or build it yourself: see [BUILD.md](BUILD.md).

### With balenaEtcher (Windows, macOS, Linux)

1. Open [balenaEtcher](https://etcher.balena.io/).
2. **Flash from file**, then pick the `.img.xz`. There's no need to unpack it;
   Etcher reads the `.xz` directly.
3. **Select target**, then your SD card. Check the size: it should be the card,
   not a USB drive or a disk.
4. **Flash!** Etcher writes the card and then verifies it.

Raspberry Pi Imager works the same way (**Choose OS → Use custom**).

The image is 1.1 GB. The rest of the card is used for your recordings.

### With dd (Linux)

Find the card's device node first. **Be certain**: `dd` to the wrong disk is
destructive.

```sh
lsblk -dpo NAME,SIZE,TRAN,MODEL     # the card is the USB/MMC one, not your NVMe/SATA
```

Then write it (replace `/dev/sdX` with your card). `dd` needs the raw image, so
unpack the release file first:

```sh
xz -dk fpvOS-vrxpro-<version>.img.xz
sudo dd if=fpvOS-vrxpro-<version>.img of=/dev/sdX bs=4M conv=fsync status=progress
sudo sgdisk -e /dev/sdX     # move the backup GPT to the end of the card
sync
```

`sgdisk -e` is optional: fpvOS does the same thing itself on first boot, but
it makes the partition table valid for the card's full size straight away.

## 2. Boot

1. Power the goggle off.
2. Put the card in.
3. Power on. The first boot takes a little longer while it settles.

You're on fpvOS when you see the fpvOS idle screen instead of the stock UI.

On the first boot fpvOS extends the partition table to the card's real size and
creates the recordings partition, ready to record straight away. That boot
takes a little longer, and the goggle may restart itself once to finish it.

Nothing on screen after a minute? See [Troubleshooting](TROUBLESHOOTING.md#the-goggle-doesnt-show-the-fpvos-idle-screen).

## 3. Link your air unit

Power the air unit. A stock Ascent air unit links to fpvOS right away, and so
does one that was bound to your goggle under stock firmware: fpvOS reads the
goggle's own pairing list, and never writes to it.

An air unit that was never bound to this goggle needs a bind. It is done from
the menu: see [the user guide](GUIDE.md#binding-an-air-unit).

## Flash the air unit (optional)

The fpvOS air image replaces the stock air app on the Ascent Lite and Lite+ with
**kestrel-air**. It is what makes the latency steady (intra refresh instead of
keyframe bursts), and what gives the end-to-end measurements on the stats
screen, the HUD that moves with the aircraft and the flight controller
telemetry. [The full list](FAQ.md#what-the-fpvos-air-image-adds).

**This is the one step that writes to your hardware.** The flasher sends the
same messages the Caddx PC tool does, to the updater already on the unit, and it
checks the image before anything is sent. Even so, it is new software: an
interrupted flash can leave a unit that has to be recovered by hand. Keep the
cable in and the unit powered until the page says it's done.

1. Download [`fpvOS-<version>-Ascent_H_Sky_18_21_10.img`](https://github.com/gehee/fpvOS/releases/latest) from the assets of the same
   [release](https://github.com/gehee/fpvOS/releases/latest). **Keep the file
   name**: the flasher and the Caddx PC tool both check that it ends in the
   stock name.
2. Open the **[fpvOS Flasher](https://gehee.github.io/fpvOS_flasher/)** in
   Chrome or Edge on a desktop computer. Nothing to install.
3. Close the Caddx PC tool and any serial terminal: only one program can open
   the port. On Linux your user needs access to `/dev/ttyACM*` (the `dialout`
   group).
4. Plug the air unit into the computer over USB, click **Connect** and pick its
   port in the browser's list.
5. Drop the `.img` on the page and read the checks it shows.
6. Click **Flash**. The unit restarts twice while it flashes. Don't unplug it
   until the page says it's done.

The Caddx PC tool flashes the same file, if you prefer it.

Lite and Lite+ take the same image: the unit tells them apart itself and the
Lite+'s camera is detected automatically.

## First flight

fpvOS is beta software and it runs the video link you fly by. Before you trust
it:

1. **Bench check.** Power both ends and look for video. Open the stats screen
   and watch the link for a minute.
2. **Record ten seconds** and play them back from the gallery. This also
   confirms the recordings partition exists.
3. **Check your channels and power.** The channel page follows your country's
   rules, but what is legal where you fly is your responsibility.
4. **Fly line-of-sight, over open ground**, until you trust it on your setup.
5. **Keep your stock card handy.** Swapping cards is your fallback.

## Updating

A new release is a new image: flash it to the card the same way. Two things to
know first:

- Flashing **erases the card**, recordings included. Copy them off first (see
  [the user guide](GUIDE.md#dvr-and-the-gallery)).
- Settings live on the card too, so they start from the defaults again.

The air unit is updated the same way: flash the newer
[`fpvOS-<version>-Ascent_H_Sky_18_21_10.img`](https://github.com/gehee/fpvOS/releases/latest).

## Going back to stock

**The goggle:** power off, remove the card, power on. The goggle boots its
internal firmware exactly as it did before: fpvOS never writes to its memory.

**The air unit:** flash Caddx's own Ascent air unit update, the same way you
flashed ours. The flasher takes Caddx's `.zip` download as it is. A unit with the
fpvOS air image that you've connected to over SSH can also be switched to the
stock app without flashing, with `touch /usrdata/fpv/air/disable`, from the
next boot.

## Connecting over USB (advanced)

You don't need this to fly. It is how you pull logs, or hot-swap a freshly built
`kestrel-gnd` while iterating.

**The goggle** exposes a USB network device. Plug it into a computer and it
comes up as a network interface; the goggle answers on **192.168.3.1**:

```sh
ssh root@192.168.3.1      # password: fpvos
```

SSH is only on the USB link. It does not answer over the goggle's WiFi access
point, so the default password is not reachable by anyone nearby.

**The air unit** (fpvOS image) does the same at **192.168.2.1** with a DHCP
server for your computer. The login is `root` / `root` by default; see
[BUILD.md](BUILD.md#the-air-unit) to set your own.

## Settings files

Settings live in `/etc/kestrel/kestrel-gnd.yaml` on the card and are editable
from the on-goggle menu. Deleting the file restores the defaults on the next
boot.

The clock shows UTC until you set your timezone: edit `TZ` in
`/etc/kestrel/time.conf` (examples for common zones are in the file), or set
it from the menu.
