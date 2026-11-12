# SPDX-License-Identifier: GPL-2.0-or-later
"""SteadyDigital install: what is checked before bank B is touched, and the order after."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_update import ROOT, SRC

BACKEND = ROOT / 'br-external/package/fpvos-update/backends/skyzone-steadydigital'


class SteadyDigitalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(); cls.build = Path(cls.temp.name)
        common = ['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-ffunction-sections', '-fdata-sections',
                  '-I' + str(SRC), '-I' + str(BACKEND), '-DP1_WORK="work"']
        renames = ['p1_preflight', 'p1_stock', 'p1_state_mount', 'p1_state_unmount', 'p1_bundle_read',
                   'p1_bundle_write', 'p1_bundle_present', 'p1_active_bank', 'p1_mtd', 'p1_gpt_read']
        subprocess.run(common + ['-D' + s + '=unused_' + s for s in renames] +
                       ['-c', str(BACKEND / 'storage.c'), '-o', str(cls.build / 'storage.o')], check=True)
        subprocess.run(common + [str(Path(__file__).with_name('sd_transaction_sim.c')), str(cls.build / 'storage.o'),
                                 str(SRC / 'bootstrap-common.c'), '-Wl,--gc-sections', '-Wl,--wrap=execlp',
                                 '-Wl,--wrap=lstat', '-o', str(cls.build / 'transaction')], check=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def transaction(self, mode):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); d = Path(temp.name)
        (d / 'work/state').mkdir(parents=True, mode=0o700)
        (d / 'volume').write_bytes(b'previous volume')
        (d / 'upload').write_bytes(b'v' * 600)
        r = subprocess.run([str(self.build / 'transaction'), mode], cwd=d, capture_output=True)
        events = (d / 'events').read_text().splitlines() if (d / 'events').exists() else []
        return d, r, events

    def test_bank_b_is_checked_before_anything_is_selected_or_written(self):
        d, r, events = self.transaction('ok')
        self.assertEqual(r.returncode, 0, r.stderr)
        order = ['verify', 'active-bank', 'bundle-present', 'select-stock', 'kernel', 'dtb', 'write', 'readback', 'activate']
        self.assertEqual([e for e in events if e in order], order)
        self.assertEqual((d / 'volume').read_bytes(), b'v' * 600)

    def test_live_stock_in_bank_b_and_an_unusable_volume_change_nothing(self):
        for fault, said in (('stock-b', b"unit's stock"), ('bad-volume', b'cannot be used'), ('gpt', b'')):
            with self.subTest(fault=fault):
                d, r, events = self.transaction(fault)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(said, r.stderr)
                for touched in ('mount', 'select-stock', 'kernel', 'dtb', 'write', 'activate'):
                    self.assertNotIn(touched, events)
                self.assertEqual((d / 'volume').read_bytes(), b'previous volume')

    def test_stock_in_bank_a_leaves_bank_b_free_whatever_it_holds(self):
        d, r, events = self.transaction('stock-a')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('activate', events)

    def test_faults_after_the_checks_never_select_bank_b(self):
        for fault in ('verify', 'gzip', 'select-stock', 'kernel', 'dtb', 'write', 'readback', 'corrupt'):
            with self.subTest(fault=fault):
                d, r, events = self.transaction(fault)
                self.assertNotEqual(r.returncode, 0)
                self.assertNotIn('activate', events)
                if fault in ('verify', 'gzip', 'select-stock', 'kernel', 'dtb'):
                    self.assertNotIn('write', events)
                    self.assertEqual((d / 'volume').read_bytes(), b'previous volume')


if __name__ == '__main__':
    unittest.main()
