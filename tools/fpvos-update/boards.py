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
    # Historical CLI spelling selects this exact board, never an SoC-wide layout.
    name = {'ar9311': 'ascent-vrx', 'ascent-gnd485': 'ascent-vrx'}.get(name, name)
    path = PACKAGE / 'backends' / name / 'profile.json'
    if not path.is_file():
        raise ValueError(f'unsupported updater board: {name}')
    return read_profile(path)
