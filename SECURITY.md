# Security

## Reporting a vulnerability

Please report security issues privately through GitHub:
**Security → Report a vulnerability** on this repository. Don't open a public
issue for them. Issues in the ground application belong to
[kestrel-gnd](https://github.com/gehee/kestrel-gnd), which takes reports the
same way.

## What is known and intended

fpvOS is a development-friendly image for a device on the pilot's own bench,
and some of its defaults are open on purpose:

- **Root login.** On the VRX Pro the root password is `fpvos`, and SSH (dropbear) is enabled.
  It is how you pull logs and swap binaries over the USB link. SSH listens on
  the USB link only (`192.168.3.1`), never on WiFi: see `/etc/default/dropbear`.
  Before the access point starts, `fpvos-wifi` also drops everything arriving
  over WiFi for port 22 or the USB link's addresses (a phone on the AP could
  otherwise route to `192.168.3.1` through the goggle); the AP does not start
  if it cannot.
- **The other devices.** The AR9311 receivers (Ascent VRX, P1 goggles,
  SteadyDigital) and the P1 Air log in as `root` / `root`, and the Ascent Lite
  and Lite+ the same unless built with your own password or keys; SSH is on
  their USB link only (192.168.3.1 for a receiver, 192.168.2.1 for an air
  unit). On the AR9311 devices the serial console (UART) gives a root shell
  without a password: it is for people with the unit open on the bench.
- **WiFi access point.** Off by default. When it is on, it uses WPA2 with the
  passphrase `12345678`, the same as stock. Change it in `/etc/fpvos/wifi-ap`
  on the goggle if other people could be in range.

Reports about these defaults are still welcome if you can show a way to
tighten them without making the goggle harder to develop on.
