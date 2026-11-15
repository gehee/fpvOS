# Ascent VRX radio configuration

`ascentvrx_defconfig` explicitly selects `radio.json` for the standard
Gnd485 / CX486-RF-2PA receiver. It does not use the VRX Pro JSON generator.
The Open8030 hardware profile is `profiles/ascent-vrx.c` from the pinned
Open8030 source, with
SDIO transport; neither the USB VRX Pro nor P1 goggles profile is suitable.
The profile must include all 29 stock 18.21.10 pin records across banks A–D.
The earlier 10-record extraction omitted banks C/D, including RF front-end
controls and their automatic I/O-domain selection. On the bench this caused
about a 6 dB receive-SNR deficit; restoring the complete pin table recovered
stock-like receive margin without changing the radio JSON or calibration.

The configuration is derived from Ascent 17.5.8's
`usr_data/fpv/boot_ar8030/bb_config_gnd.json` (source SHA-256
`57937939f46d039e015aa3d8d55ecfb2012de4b3a13dd45b9af652d96a3ab391`).
JSON values are unchanged; whitespace is normalized. The MAC strings are
vendor placeholders, not captured device identities. Open8030 uses hardware
OTP identity and Kestrel supplies the selected peer.

This baseline retains the stock power tables, LNA settings, channel plan,
MCS thresholds and disabled automatic bandwidth policy. The previous default
used VRX Pro's configuration with `gnd-config.py` tuning: automatic bandwidth
and modified MCS/LDPC thresholds. Although the stock standard-board power
and LNA tables match, that does not establish equivalent RF performance.
Kestrel can override channel, power, bandwidth, frame mode and rate settings
at runtime; inspect those as well when comparing reception.

Unit-specific power offsets are read by Open8030 from the radio's factory
flash, not copied into this JSON or supplied by the Linux factory merger used
on P1. The firmware can fall back to defaults for unavailable/unsupported
factory records, so initialization alone does not prove calibrated operation.
Inspect its boot diagnostics to verify the calibration source and offsets.

Stock also contains CX420 variants with different RF tables. Those need
separate validated profiles; selecting one based only on a channel frequency
is incorrect. This profile is not a claim of support for those variants.

Configuration parsing and package installation can be tested without running
an RF link. Range and packet-loss performance require comparison on hardware
at the same channel, width, frame mode, air power and antenna placement.
