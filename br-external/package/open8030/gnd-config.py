#!/usr/bin/env python3
"""gnd-config.py <stock bb_config_gnd_pro.json> <output>

The goggle radio's configuration under Open8030: the stock VRX Pro file with
fpvOS's link tuning (automatic width on, and its MCS table)."""
import json
import sys

# Thresholds in the stock file's SNR units; one row per MCS the goggle may ask for.
MCS_TAB = [
    {"mcs": -1, "snr_up": 36, "snr_dw": 29},
    {"mcs": 0, "snr_up": 92, "snr_dw": 65, "up_keep_time": 1500},
    {"mcs": 3, "snr_up": 168, "snr_dw": 119, "up_keep_time": 1500},
    {"mcs": 5, "snr_up": 303, "snr_dw": 241, "up_keep_time": 800},
    {"mcs": 6, "snr_up": 598, "snr_dw": 475, "up_keep_time": 800},
    {"mcs": 8, "snr_up": 1192, "snr_dw": 947, "dw_keep_time": 12},
    {"mcs": 10, "snr_up": 1846, "snr_dw": 1466, "dw_keep_time": 1},
    {"mcs": 11, "snr_up": 3682, "snr_dw": 2925, "dw_keep_time": 12},
]
ROW = {"ldpc_up_num": 3, "ldpc_dw_num": 6, "ldpc_dw_conti_num": 6,
       "up_keep_time": 1000, "dw_keep_time": 15}
ORDER = ["mcs", "snr_up", "snr_dw", "ldpc_up_num", "ldpc_dw_num",
         "ldpc_dw_conti_num", "up_keep_time", "dw_keep_time"]


def main(stock, output):
    try:
        with open(stock) as f:
            config = json.load(f)
    except OSError as e:
        sys.exit(f"gnd-config: {e} - run the VRX Pro firmware extractor, "
                 "or set OPEN8030_STOCK_GND_CONFIG")
    try:
        if config["baseband"]["basic"]["role"] != "dev":
            sys.exit(f"{stock}: not a ground (dev role) configuration")
        slot = config["baseband"]["basic"]["dev"]["mcs"]["slot"]
        slot["bw_auto"]["enable"]
        slot["mcs_tab"]
    except (KeyError, TypeError) as e:
        sys.exit(f"{stock}: no baseband.basic.dev.mcs.slot {e} - not the stock layout")
    slot["bw_auto"]["enable"] = True
    slot["mcs_tab"] = [{k: {**ROW, **row}[k] for k in ORDER} for row in MCS_TAB]
    with open(output, "w") as f:
        f.write(json.dumps(config, indent=1))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
