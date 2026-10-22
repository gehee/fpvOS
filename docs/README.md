# fpvOS documentation

## For flying

| Read | When |
|---|---|
| [Installing](INSTALL.md) | You have a VRX Pro and want fpvOS on it, from download to first flight. Also updating, and going back to stock. |
| [User guide](GUIDE.md) | You're on fpvOS and want to know what the buttons, the menu, the DVR, the stats screen and the WiFi view do. |
| [FAQ](FAQ.md) | Will it brick it, do I need the air image, does it work with my gear, is it legal. |
| [Latency](LATENCY.md) | What each display setting costs in latency and smoothness, measured glass to glass, and which to pick. |
| [Troubleshooting](TROUBLESHOOTING.md) | Something doesn't look right. Symptom, cause, fix, and the known issues. |

Still stuck? [SUPPORT.md](../SUPPORT.md) says where to ask and what to include.

## For building and changing it

| Read | When |
|---|---|
| [About](ABOUT.md) | You want to know why fpvOS exists, what is open and what isn't, how the repositories fit together, and where it is going. |
| [Building](BUILD.md) | You want to build the goggle and air images from source. |
| [Architecture](ARCHITECTURE.md) | You want to know how the stack fits together and where to change what. |
| [The kernel](KERNEL.md) | You're touching Linux 6.12, stream decode or the board driver. |
| [Contributing](../CONTRIBUTING.md) | You want to send a change. |

The applications have their own repositories, with their own developer notes:
[kestrel-gnd](https://github.com/gehee/kestrel-gnd) (the goggle),
[kestrel-air](https://github.com/gehee/kestrel-air) (the air unit),
[ar_libre](https://github.com/gehee/ar_libre) (the radio's host stack) and the
[fpvOS Flasher](https://github.com/gehee/fpvOS_flasher).
