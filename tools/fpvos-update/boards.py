# SPDX-License-Identifier: GPL-2.0-or-later
"""Select an explicitly supported board; never infer a flash layout from USB."""
import importlib.util
from pathlib import Path
import re

PACKAGE = Path(__file__).resolve().parents[2] / 'br-external/package/fpvos-update'
_spec = importlib.util.spec_from_file_location('fpvos_board_profile', PACKAGE / 'board_profile.py')
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
read_profile = _module.read_profile


def get_profile(name):
    if not re.fullmatch('[a-z0-9][a-z0-9_-]*', name):
        raise ValueError('invalid board name')
    # A backend of its own keeps its profile.json; boards sharing the serial
    # backend (the VRX Pro) keep theirs as backends/serial/<board>.json, as
    # its backend.mk reads it.
    for path in (PACKAGE / 'backends' / name / 'profile.json',
                 PACKAGE / 'backends' / 'serial' / f'{name}.json'):
        if path.is_file():
            return read_profile(path)
    raise ValueError(f'unsupported updater board: {name}')
