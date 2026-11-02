# SPDX-License-Identifier: GPL-2.0-or-later
"""P1 recovery selection and activation ordering, with file-backed UBI faults."""
import os
import runpy
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib
from test_update import ROOT, SRC

BACKEND = ROOT / 'br-external/package/fpvos-update/backends/p1-air'
PARTS = [('vendor',0x180000,0x80000,1),('factory',0x200000,0x600000,1),
         ('env0',0x800000,0x60000,0),('env1',0x860000,0x60000,1),
         ('uboot0',0x8c0000,0xc0000,0),('uboot1',0x980000,0xc0000,1),
         ('kernel0',0xa40000,0x600000,0),('kernel1',0x1040000,0x600000,1),
         ('dtb0',0x1640000,0x60000,0),('dtb1',0x16a0000,0x60000,1),
         ('userapp0',0x1700000,0x2d00000,0),('userapp1',0x4400000,0x2d00000,1),
         ('usr_data',0x7100000,0x600000,1),('usr_log',0x7700000,0x600000,1)]


def record(slot=1,generation=1,parts=PARTS):
    entries=bytearray(16384)
    for i,(name,start,size,active) in enumerate(parts):
        struct.pack_into('<QQQ',entries,i*128+32,start//512,(start+size)//512-1,active<<47)
        entries[i*128+56:i*128+56+len(name)*2]=name.encode('utf-16le')
    h=bytearray(512);h[:8]=b'EFI PART'
    struct.pack_into('<IIII',h,8,0x10000,92,0,generation)
    struct.pack_into('<QQQQ',h,24,0x3f7ff if slot else 1,1 if slot else 0x3f7ff,0xc00,0x3f7de)
    struct.pack_into('<QIII',h,72,0x3f7df if slot else 2,128,128,zlib.crc32(entries))
    struct.pack_into('<I',h,16,zlib.crc32(h[:92]))
    return bytes(512)+h+entries


class P1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.build=Path(cls.temp.name)
        common=['cc','-O2','-Wall','-Wextra','-Werror','-ffunction-sections','-fdata-sections','-I'+str(SRC),'-DP1_WORK="work"']
        renames=['p1_preflight','p1_stock','p1_state_mount','p1_state_unmount','p1_bundle_read','p1_bundle_write','p1_mtd','p1_gpt_read']
        subprocess.run(common+['-D'+s+'=unused_'+s for s in renames]+['-c',str(BACKEND/'storage.c'),'-o',str(cls.build/'storage.o')],check=True)
        subprocess.run(common+[str(Path(__file__).with_name('p1_transaction_sim.c')),str(cls.build/'storage.o'),str(SRC/'bootstrap-common.c'),'-Wl,--gc-sections','-Wl,--wrap=execlp','-Wl,--wrap=lstat','-o',str(cls.build/'transaction')],check=True)
        subprocess.run(common+[str(Path(__file__).with_name('p1_flash_sim.c')),str(cls.build/'storage.o'),'-Wl,--gc-sections','-Wl,--wrap=open','-Wl,--wrap=ioctl','-Wl,--wrap=pwrite','-Wl,--wrap=fsync','-o',str(cls.build/'flash')],check=True)
        (cls.build/'layout.c').write_text('#include <stdio.h>\n#include "'+str(BACKEND/'layout.h')+'"\nint main(void) { unsigned char g[2][AR9311_GPT_BYTES]; if (fread(g,1,sizeof(g),stdin)!=sizeof(g)) return 2; return !p1_layout_valid(g); }\n')
        subprocess.run(common+[str(cls.build/'layout.c'),'-o',str(cls.build/'layout')],check=True)

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def layout(self,a,b):
        return subprocess.run([str(self.build/'layout')],input=a+b).returncode==0

    def test_stock_bank_one_and_redundant_generation(self):
        erased=b'\xff'*0x4400
        self.assertTrue(self.layout(erased,record()))
        self.assertTrue(self.layout(record(0,2),record()))
        self.assertTrue(self.layout(record(0),record()))
        self.assertFalse(self.layout(erased,erased))

    def test_wrong_bank_geometry_names_and_torn_metadata_rejected(self):
        for index in range(len(PARTS)):
            for field in (0,1,2,3):
                parts=list(PARTS);item=list(parts[index])
                item[field]=('unknown' if field==0 else item[field]+512 if field in (1,2) else 1-item[field])
                parts[index]=tuple(item)
                with self.subTest(part=index,field=field):
                    self.assertFalse(self.layout(b'\xff'*0x4400,record(parts=parts)))
        damaged=bytearray(record());damaged[528]^=1
        self.assertTrue(self.layout(record(0),damaged))
        parts=list(PARTS);parts[-1]=parts[-2]
        self.assertFalse(self.layout(record(0),record(parts=parts)))

    def flash_directory(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);d=Path(temp.name)
        data=bytearray(b'\xff'*0x80000);data[0x40000:0x44400]=record()
        (d/'boot-state').write_bytes(data)
        (d/'kernel0').write_bytes(b'\x55'*0x600000)
        (d/'dtb0').write_bytes(b'\x55'*0x60000)
        return d

    def flash(self,d,operation,arg,fault=0):
        return subprocess.run([str(self.build/'flash'),operation,str(arg),str(fault)],cwd=d).returncode

    def test_direct_selection_and_return_preserve_other_metadata(self):
        d=self.flash_directory();before=(d/'boot-state').read_bytes()
        self.assertEqual(self.flash(d,'select',0),0)
        after=(d/'boot-state').read_bytes()
        self.assertEqual(after[0x40000:],before[0x40000:])
        self.assertTrue(self.layout(after[:0x4400],after[0x40000:0x44400]))
        for i in range(14):
            old=before[0x40400+i*128:0x40400+(i+1)*128]
            new=after[1024+i*128:1024+(i+1)*128]
            if 6<=i<=11:
                self.assertEqual(new[:48]+new[56:],old[:48]+old[56:])
                self.assertEqual(struct.unpack_from('<Q',new,48)[0],(1-(i%2))<<47)
            else: self.assertEqual(new,old)
        self.assertEqual(self.flash(d,'select',1),0)
        end=(d/'boot-state').read_bytes()
        self.assertEqual(end[:0x40000],after[:0x40000])
        self.assertEqual(end[0x40400:0x44400],before[0x40400:0x44400])

    def test_torn_gpt_keeps_previous_record_and_can_retry(self):
        for fault in (1,3,4):
            with self.subTest(fault=fault):
                d=self.flash_directory();before=(d/'boot-state').read_bytes()
                self.assertNotEqual(self.flash(d,'select',0,fault),0)
                after=(d/'boot-state').read_bytes()
                self.assertEqual(after[0x40000:],before[0x40000:])
                self.assertTrue(self.layout(after[:0x4400],after[0x40000:0x44400]))
                self.assertEqual(self.flash(d,'select',0),0)

    def test_nand_bad_block_skipping_readback_and_errors(self):
        d=self.flash_directory();image=bytes(range(256))*1200;(d/'image').write_bytes(image)
        self.assertEqual(self.flash(d,'write','image',2),0)
        data=(d/'kernel0').read_bytes()
        self.assertEqual(data[:0x20000],image[:0x20000])
        self.assertEqual(data[0x20000:0x40000],b'\x55'*0x20000)
        self.assertEqual(data[0x40000:0x40000+len(image)-0x20000],image[0x20000:])
        self.assertEqual(self.flash(d,'compare','image',2),0)
        for fault in (1,3,4):
            self.assertNotEqual(self.flash(d,'write','image',fault),0)

    def transaction(self,mode):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);d=Path(temp.name)
        (d/'work/state/fpvos-boot').mkdir(parents=True,mode=0o700)
        (d/'work/state/fpvos-boot/owner').write_text('fpvOS P1 boot agent 1\n')
        (d/'work/state/fpvos-boot/fpvos-update').write_bytes(b'old agent')
        (d/'work/state/sirius-clean-system-flag').write_text('web:/usrdata/fpvos-boot/boot.sh\n' if mode!='foreign' else 'usb:vendor\n')
        (d/'volume').write_bytes(b'previous volume')
        (d/'upload').write_bytes(b'valid verified snapshot')
        # Production requires root-owned files; simulate that one metadata bit
        # for this filesystem harness using a separately compiled shim below.
        r=subprocess.run([str(self.build/'transaction'),mode],cwd=d,capture_output=True)
        return d,r,(d/'events').read_text().splitlines()

    def test_verified_readback_precedes_boot_activation(self):
        d,r,events=self.transaction('ok')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertLess(events.index('select-stock'),events.index('kernel'))
        self.assertLess(events.index('kernel'),events.index('dtb'))
        self.assertLess(events.index('dtb'),events.index('write'))
        self.assertLess(events.index('write'),events.index('readback'))
        self.assertLess(events.index('readback'),events.index('activate'))
        self.assertEqual((d/'volume').read_bytes(),b'valid verified snapshot')
        self.assertFalse((d/'work/state/fpvos-boot/disabled').exists())

    def test_faults_never_arm_or_overwrite_stock_selection(self):
        for fault in ('verify','gzip','select-stock','kernel','dtb','write','readback','corrupt','foreign'):
            with self.subTest(fault=fault):
                d,r,events=self.transaction(fault)
                self.assertNotEqual(r.returncode,0)
                self.assertNotIn('activate',events)
                if fault in ('verify','gzip','select-stock','kernel','dtb','foreign'):
                    self.assertNotIn('write',events)
                    self.assertEqual((d/'volume').read_bytes(),b'previous volume')
                if fault=='write':
                    self.assertEqual((d/'volume').read_bytes(),b'torn update')
                if fault in ('write','readback','corrupt'):
                    self.assertFalse((d/'work/state/sirius-clean-system-flag').exists())

    def test_changed_upload_cannot_replace_verified_snapshot(self):
        d,r,events=self.transaction('mutate')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual((d/'upload').read_bytes(),b'changed')
        self.assertEqual((d/'volume').read_bytes(),b'valid verified snapshot')

class BootGuardTests(unittest.TestCase):
    def test_entry_preserves_header_and_returns_to_original_branch(self):
        mod = runpy.run_path(str(ROOT / 'boot/p1-bootguard.py'))
        image = bytearray(256)
        image[56:60] = b'ARM\x64'
        struct.pack_into('<I', image, 4, 0x14000010)
        struct.pack_into('<Q', image, 16, 4096)
        code = bytes(56) + mod['branch'](0)
        result = mod['guard'](bytes(image), code)
        self.assertEqual(result[4:256], image[4:])
        def target(pc):
            imm = struct.unpack_from('<I', result, pc)[0] & 0x3ffffff
            if imm & (1 << 25): imm -= 1 << 26
            return pc + 4 * imm
        self.assertEqual(target(0), len(image))
        self.assertEqual(target(len(result)-4), 4)
        struct.pack_into('<Q', image, 16, 256)
        with self.assertRaises(ValueError): mod['guard'](bytes(image), code)
        struct.pack_into('<Q', image, 16, 4096)
        struct.pack_into('<Q', image, 8, 0x80000)
        with self.assertRaises(ValueError): mod['guard'](bytes(image), code)

if __name__=='__main__': unittest.main()
