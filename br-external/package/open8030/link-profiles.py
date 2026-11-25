#!/usr/bin/env python3
"""Add the link profiles to the ground radio config the build made.

The profiles differ only in Open8030's own rules (Open8030
docs/configuration.md, dev.mcs.slot.open8030): the errored-frame rule and the
40 MHz MCS cap. All three go into the one config, as open8030.profiles, in
kestrel-gnd's RADIO > Link Profile order (0 LOW LATENCY, 1 BALANCED, 2
QUALITY); the radio starts on BALANCED and kestrel-gnd switches it live with
request 0x0c5a0038, no restart.

  link-profiles.py <open8030.json> <out.json>
"""
import json
import sys

PROFILES = {
    # Errored frames kept rare, so resends and their latency too: the rule
    # as it was built in until 2026-11-16 (a row losing more than 2 of 256
    # frames is left, barred 10 s, doubling to 80 s). Indoors it can hold
    # the MCS at its lowest.
    "lowlatency": {
        "error_rule": {"enable": True, "frames": 256, "errors": 2, "hold_ms": 10000, "hold_max_ms": 80000},
        "wide": {"max_mcs": 8},
    },
    # No errored-frame rule, MCS 8 at 40 MHz. Indoors (2026-11-16) a limit on
    # errored frames only parked the link where the room's errors reached it
    # (2.5%: 8.3 Mbit/s, 5%: 9.1), while resends repaired every errored
    # frame; most of QUALITY's errors and late pictures come from MCS 10.
    "balanced": {
        "error_rule": {"enable": False},
        "wide": {"max_mcs": 8},
    },
    # No errored-frame rule (as beta4): the MCS follows the SNR rows and
    # resends repair what is lost. MCS 10 at 40 MHz.
    "quality": {
        "error_rule": {"enable": False},
        "wide": {"max_mcs": 10},
    },
}
ORDER = ("lowlatency", "balanced", "quality")   # kestrel-gnd's ar8030_link_profile 0, 1, 2
DEFAULT = 1


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    with open(sys.argv[1]) as f:
        base = json.load(f)
    slot = base["baseband"]["basic"]["dev"]["mcs"]["slot"]
    slot["open8030"] = {"profile": DEFAULT,
                        "profiles": [dict(name=name, **PROFILES[name]) for name in ORDER]}
    with open(sys.argv[2], "w") as f:
        json.dump(base, f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main()
