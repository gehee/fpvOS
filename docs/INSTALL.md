# Installing fpvOS

fpvOS boots the Caddx / Ascent VRX Pro from an SD card, leaving the stock
firmware on the goggle's internal NAND untouched. Pull the card and the goggle
boots stock again — so trying fpvOS is low-risk and fully reversible.

> **You build the image yourself** — see [BUILD.md](BUILD.md). fpvOS does not
> distribute images with vendor firmware in them. The build produces
> `sdcard.img`.

## Flash the card

Any SD card ≥ 2 GB. Find its device node first — **be certain**, `dd` to the
wrong disk is destructive:

```sh
lsblk -dpo NAME,SIZE,TRAN,MODEL     # the card is the USB/MMC one, not your NVMe/SATA
```

Then write it (replace `/dev/sdX` with your card):

```sh
sudo dd if=sdcard.img of=/dev/sdX bs=4M conv=fsync status=progress
sudo sgdisk -e /dev/sdX     # move the backup GPT to the end of the card
sync
```

`sgdisk -e` is optional but tidy — it makes the partition table valid for the
card's full size instead of just the image's 1.1 GB.

## Boot

1. Power the goggle off.
2. Insert the card.
3. Power on. First boot takes a little longer while it settles.

You're on fpvOS when you see the kestrel idle screen instead of the stock UI.

## Connect over USB

The goggle exposes a USB CDC-ECM network gadget. Plug it into a host and it
comes up as a network interface; the goggle answers on **192.168.3.1**:

```sh
ssh root@192.168.3.1      # password: fpvos
```

SSH is only on the USB link. It does not answer over the goggle's WiFi access
point, so the default password is not reachable by anyone nearby.

This is how you pull logs, extract vendor blobs for a build
([BUILD.md](BUILD.md)), or hot-swap a freshly built `kestrel-gnd` while
iterating.

## Go back to stock

Power off, remove the card, power on. The goggle boots its internal firmware
exactly as it did before — fpvOS never writes to NAND.

## Settings

Settings live in `/etc/kestrel/kestrel-gnd.yaml` on the card and are editable
from the on-goggle menu (display style, HUD detail, camera, link). Deleting the
file restores defaults on next boot.

The clock shows UTC until you set your timezone: edit `TZ` in
`/etc/kestrel/time.conf` (examples for common zones are in the file).
