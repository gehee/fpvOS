#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Adapt pinned P1 stock defaults to the validated Open8030 AP transport.

The vendor app normally supplies these settings. Do not include bench peer IDs
or factory offsets: Open8030 reads its OTP identity, Kestrel manages peers, and
radio-calibrate supplies the individual unit's power offsets at runtime.
"""
import json
import sys
from pathlib import Path


def configure(config):
    basic = config["baseband"]["basic"]
    basic["role"] = "ap"
    basic["ap"]["mcs"]["slot"]["init"] = -1
    basic["ap"]["candidate"]["slot"] = []
    # Parsed as a placeholder; Open8030 replaces this with the radio OTP ID.
    basic["ap"]["mac"] = "00000000"
    basic["dev"]["ap_mac"] = "00000000"
    # The goggle's list (bb_config_gnd_open8030.json): air and ground name
    # channels by index, so the order must match. 5839000 at index 15 is not
    # a typo; the stock Caddx ground lists have it there too.
    basic["channel"]["freq"] = [
        4915000, 4945000, 4975000, 5005000, 5035000, 5065000,
        5120000, 5160000, 5200000, 5240000, 5275000, 5320000,
        5360000, 5400000, 5440000, 5839000, 5475000, 5510000,
        5545000, 5580000, 5620000, 5660000, 5695000, 5740000,
        5770000, 5805000, 5878000, 5914000, 5955000, 5985000,
        6015000, 6045000, 6075000, 6110000, 6145000, 6180000,
        6220000, 6255000, 6290000, 6325000, 6360000, 6395000,
    ]
    basic["channel"]["init_chan"] = 25
    slot = basic["para"]["slot"]
    for direction in ("tx", "rx"):
        slot[direction].update(tintlv_len=12, tintlv_num=1, bandwidth="2.5")
    slot["rx"]["rx_mode"] = "1T1R"
    slot["tx"]["retx_count"] = 6
    broadcast = basic["para"]["br"]
    for direction in ("tx", "rx"):
        broadcast[direction].update(tintlv_len=12, tintlv_num=2, bandwidth="5")
    broadcast["rx"].update(enable_tintlv=True, rx_mode="2T2R_STBC")
    broadcast["tx"].update(retx_count=100, tx_mode="2TX_STBC")
    basic["power"]["pwr_init"] = 23
    basic["power"].pop("pwr_offset", None)
    config["sync_config"]["enable"] = 0
    return config


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: configure.py STOCK.json OUTPUT.json")
    source, output = map(Path, sys.argv[1:])
    output.write_text(json.dumps(configure(json.loads(source.read_text())),
                                 separators=(",", ":"), sort_keys=True) + "\n")
