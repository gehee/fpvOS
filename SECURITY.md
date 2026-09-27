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

- **Root login.** The root password is `fpvos`, and SSH (dropbear) is enabled.
  It is how you pull logs and swap binaries over the USB link. SSH listens on
  the USB link only (`192.168.3.1`), never on WiFi: see `/etc/default/dropbear`.
- **WiFi access point.** Off by default. When it is on, it uses WPA2 with the
  passphrase `12345678`, the same as stock. Change it in `/etc/fpvos/wifi-ap`
  on the goggle if other people could be in range.

Reports about these defaults are still welcome if you can show a way to
tighten them without making the goggle harder to develop on.
