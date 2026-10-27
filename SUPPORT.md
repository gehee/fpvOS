# Getting help

fpvOS is built and supported by a small community, on a best-effort basis.
Nobody is on call, so there is no promised response time, but a clear report
gets read.

## Start here

1. **[Troubleshooting](docs/TROUBLESHOOTING.md)**: what you see, what it means
   and what to do. Most first-flight problems are on that page.
2. **[Installing](docs/INSTALL.md)** and the **[user guide](docs/GUIDE.md)** if
   you're not sure how something is meant to work.
3. **The release notes** of your version, under
   [Releases](https://github.com/gehee/fpvOS/releases): they list the known
   issues of that release.

## Ask

**[Discord](https://discord.gg/CXhNKYFF2v)** is the place for questions, for
"is this normal?", for showing a flight and for new hardware. Say which goggle,
which air unit, which fpvOS version and what you see.

## Report a bug

If it can be reproduced, open an issue. Pick the right repository:

| What is wrong | Where |
|---|---|
| Anything on screen (HUD, menus, DVR, gallery, stats), video, the link | [kestrel-gnd](https://github.com/gehee/kestrel-gnd/issues) |
| The air unit's camera, encoder or link | [kestrel-air](https://github.com/gehee/kestrel-air/issues) |
| The image: boot, install, build, WiFi, the card | [fpvOS](https://github.com/gehee/fpvOS/issues/new/choose) |
| The air unit flasher | [fpvOS_flasher](https://github.com/gehee/fpvOS_flasher/issues) |
| The radio driver | [ar_libre](https://github.com/gehee/ar_libre/issues) |

Not sure? Use fpvOS; it will be moved if it belongs elsewhere.

A report is fixable when it says:

- your **goggle and air unit** (VRX Pro, Ascent Lite or Lite+, stock or fpvOS
  air image) and the **fpvOS version**,
- **what you did and what happened**, and what you expected,
- whether it happens **every time**, and whether it does on a stock card,
- the **logs**: how to get them is in
  [Troubleshooting](docs/TROUBLESHOOTING.md#collecting-logs).

Don't post `/factory/user_cfg.json`: it lists the air units your goggle is paired
with.

## Security

Please don't open a public issue for a vulnerability: see [SECURITY.md](SECURITY.md).

## Contribute

Fixes, hardware and docs are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).
