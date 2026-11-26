# SPDX-License-Identifier: GPL-2.0-or-later
"""The Nano VRX uses the shared P1 backend in the P1 Air's bank orientation."""
from pathlib import Path
import unittest
import test_p1 as p1
from test_p1 import ROOT


class NanoVrxTests(p1.P1Tests):
    config_flags = ['-include', str(ROOT / 'br-external/package/fpvos-update/backends/p1-nano-vrx/config.h')]
    kernel_name = b'fpvOS P1 Nano VRX recovery'


del p1  # only NanoVrxTests is collected from this module

if __name__ == '__main__': unittest.main()
