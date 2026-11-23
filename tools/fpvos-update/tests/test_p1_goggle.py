# SPDX-License-Identifier: GPL-2.0-or-later
"""Goggles config (bank-0 U-Boot pair, larger root) and write faults exercise
the shared P1 backend; the install bank is chosen per unit, as on the P1 Air."""
from pathlib import Path
import subprocess
import tempfile
import unittest
import test_p1 as p1
from test_p1 import PARTS, record, ROOT


class GoggleTests(unittest.TestCase):
    config_flags = ['-include', str(ROOT / 'br-external/package/fpvos-update/backends/p1-goggle/config.h')]
    setUpClass = classmethod(p1.P1Tests.setUpClass.__func__)
    tearDownClass = classmethod(p1.P1Tests.tearDownClass.__func__)
    app_partition = ("userapp1",0x4400000)
    volume = p1.P1Tests.volume
    test_stock_volume_names = p1.P1Tests.test_stock_volume_names
    transaction = p1.P1Tests.transaction
    TARGETS = p1.P1Tests.TARGETS
    test_bank_and_volume_are_checked_before_anything_changes = p1.P1Tests.test_bank_and_volume_are_checked_before_anything_changes
    test_the_target_bank_is_chosen_from_what_each_bank_holds = p1.P1Tests.test_the_target_bank_is_chosen_from_what_each_bank_holds
    test_booted_stock_is_never_written = p1.P1Tests.test_booted_stock_is_never_written
    test_an_unusable_target_volume_or_gpt_changes_nothing = p1.P1Tests.test_an_unusable_target_volume_or_gpt_changes_nothing
    test_stock_selects_the_bank_without_fpvos = p1.P1Tests.test_stock_selects_the_bank_without_fpvos
    flash = p1.P1Tests.flash
    layout = p1.P1Tests.layout

    def directory(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        d = Path(temp.name)
        parts = [(n,o,s,1-a if n.startswith(('env','uboot','kernel','dtb','userapp')) else a) for n,o,s,a in PARTS]
        data = bytearray(b'\xff' * 0x80000)
        data[:0x4400] = record(0, 1, parts)
        (d/'boot-state').write_bytes(data)
        (d/'kernel1').write_bytes(b'\x55' * 0x600000)
        (d/'dtb1').write_bytes(b'\x55' * 0x60000)
        return d

    def test_select_bank_one_preserves_stock_and_bootloader_selection(self):
        d=self.directory();before=(d/'boot-state').read_bytes()
        self.assertEqual(self.flash(d,'select',1),0)
        after=(d/'boot-state').read_bytes()
        self.assertEqual(after[:0x40000],before[:0x40000])
        self.assertTrue(self.layout(after[:0x4400],after[0x40000:0x44400]))
        for i in list(range(6))+[12,13]:
            self.assertEqual(after[0x40400+i*128:0x40400+(i+1)*128],before[1024+i*128:1024+(i+1)*128])
        self.assertEqual(self.flash(d,'select',0),0)
        end=(d/'boot-state').read_bytes()
        self.assertEqual(end[1024:0x4400],before[1024:0x4400])

    def test_torn_gpt_keeps_stock_record(self):
        for fault in (1,3,4,5):
            with self.subTest(fault=fault):
                d=self.directory();before=(d/'boot-state').read_bytes()
                self.assertNotEqual(self.flash(d,'select',1,fault),0)
                after=(d/'boot-state').read_bytes()
                self.assertEqual(after[:0x40000],before[:0x40000])
                self.assertTrue(self.layout(after[:0x4400],after[0x40000:0x44400]))

    def test_kernel_write_to_bank_one_leaves_its_dtb(self):
        d=self.directory();image=bytes(range(256))*1200;(d/'image').write_bytes(image)
        self.assertEqual(self.flash(d,'write','image',bank=1),0)
        self.assertEqual((d/'kernel1').read_bytes()[:len(image)],image)
        self.assertEqual((d/'dtb1').read_bytes(),b'\x55'*0x60000)

    test_faults_never_arm_or_overwrite_stock_selection = p1.P1Tests.test_faults_never_arm_or_overwrite_stock_selection
    test_changed_upload_cannot_replace_verified_snapshot = p1.P1Tests.test_changed_upload_cannot_replace_verified_snapshot


if __name__ == '__main__': unittest.main()
