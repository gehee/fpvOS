#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate a const C profile from the same board JSON used by host tools."""
import json
from pathlib import Path
import sys
from board_profile import read_profile

p = read_profile(sys.argv[1])
legacy = p.get('legacy_destination', '')
string = json.dumps
text = '/* Generated from board profile; do not edit. */\n#include "board.h"\n'
text += 'const struct fpvos_update_board fpvos_board = {\n'
for name, value in (('board_id', str(p['board_id'])), ('hardware', string(p['hardware'])),
                    ('usb_serial', string(p['usb_identity'][2])),
                    ('legacy_install_destination', string(legacy + '.fwu' if legacy else '')),
                    ('legacy_verify_destination', string(legacy + '.verify' if legacy else '')),
                    ('names', '{' + ', '.join(map(string, p['names'])) + '}'),
                    ('limits', '{' + ', '.join(map(str, p['limits'])) + '}'),
                    ('counts', '{' + ', '.join(map(str, p['counts'])) + '}'),
                    ('bundle_limits', '{' + ', '.join(map(str, p['bundle_limits'])) + '}')):
    text += f'    .{name} = {value},\n'
text += '};\n'
Path(sys.argv[2]).write_text(text)
