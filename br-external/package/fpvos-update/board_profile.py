# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared profile reader for the build-time C generator and host tools."""
import json
from pathlib import Path
import re


def read_profile(path):
    profile = json.loads(Path(path).read_text())
    if not 0 < profile['board_id'] <= 0xffffffff:
        raise ValueError('invalid board ID')
    names, limits, counts = (profile[key] for key in ('names', 'limits', 'counts'))
    if not 1 <= len(names) <= 3 or len(set(names)) != len(names) or len(limits) != len(names):
        raise ValueError('invalid component table')
    for name in names:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,30}', name):
            raise ValueError('invalid component name')
    if any(not 0 < limit <= 64*1024*1024 for limit in limits):
        raise ValueError('invalid component limit')
    if len(counts) != 2 or counts[0] != len(names) or not 0 <= counts[1] <= len(names):
        raise ValueError('invalid component counts')
    if len(profile['bundle_limits']) != 2 or any(not 512 <= n <= 64*1024*1024 for n in profile['bundle_limits']):
        raise ValueError('invalid bundle limit')
    for value in (profile['hardware'], profile['usb_identity'][2]):
        if not value or len(value) > 31 or not value.isascii() or not value.isprintable():
            raise ValueError('invalid device identity')
    if len(profile['usb_identity']) != 3 or any(not re.fullmatch('[0-9a-f]{4}', v) for v in profile['usb_identity'][:2]):
        raise ValueError('invalid USB identity')
    legacy = profile.get('legacy_destination', '')
    if legacy and (not re.fullmatch(r'/tmp/pc/[A-Za-z0-9_.-]+', legacy) or len(legacy) > 110):
        raise ValueError('invalid legacy destination')
    sources = profile.get('restore_sources', [])
    if len(sources) != counts[1] or any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', n) for n in sources):
        raise ValueError('invalid restore sources')
    return profile
