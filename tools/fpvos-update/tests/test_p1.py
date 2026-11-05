# SPDX-License-Identifier: GPL-2.0-or-later
"""P1 recovery selection and activation ordering, with file-backed UBI faults."""
import os
import runpy
import shutil
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
        subprocess.run(common+[str(Path(__file__).with_name('p1_flash_sim.c')),str(cls.build/'storage.o'),'-Wl,--gc-sections','-Wl,--wrap=open','-Wl,--wrap=ioctl','-Wl,--wrap=pwrite','-Wl,--wrap=pread','-Wl,--wrap=fsync','-o',str(cls.build/'flash')],check=True)
        subprocess.run(common+[str(Path(__file__).with_name('p1_volume_sim.c')),'-Wl,--gc-sections','-Wl,--wrap=open','-Wl,--wrap=__open_2','-Wl,--wrap=opendir','-Wl,--wrap=access','-Wl,--wrap=ioctl','-o',str(cls.build/'volume')],check=True)
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

    def volume(self,kind,data='usrdata',app='userapp'):
        with tempfile.TemporaryDirectory() as t:
            d=Path(t)
            for n,(mtd,offset,size,name,ebs) in enumerate((('usr_data',0x7100000,0x600000,data,40),('userapp0',0x1700000,0x2d00000,app,353))):
                for path,text in {f'sys/class/mtd/mtd{n}/name':mtd,f'sys/class/mtd/mtd{n}/offset':str(offset),
                                  f'sys/class/ubi/ubi{n}/mtd_num':str(n),f'sys/class/ubi/ubi{n}/ro_mode':'0',
                                  f'sys/class/ubi/ubi{n}_0/name':name,f'sys/class/ubi/ubi{n}_0/type':'dynamic',
                                  f'sys/class/ubi/ubi{n}_0/reserved_ebs':str(ebs),
                                  f'sys/class/ubi/ubi{n}_0/usable_eb_size':'126976',f'dev/ubi{n}_0':''}.items():
                    (d/path).parent.mkdir(parents=True,exist_ok=True);(d/path).write_text(text+'\n' if text else '')
                with open(d/f'dev/mtd{n}','wb') as f: f.truncate(size)
            r=subprocess.run([str(self.build/'volume'),kind],cwd=d,capture_output=True,text=True)
            return r.stdout.strip() if r.returncode==0 else None

    def test_stock_volume_names(self):
        # As on a stock 1.0.44 unit: MTD usr_data holds volume usrdata, userapp0 holds userapp.
        self.assertEqual(self.volume('data'),'/dev/ubi0_0')
        self.assertEqual(self.volume('app'),'/dev/ubi1_0')
        self.assertIsNone(self.volume('data',data='usr_data'))
        self.assertIsNone(self.volume('app',app='userapp0'))

    def flash_directory(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);d=Path(temp.name)
        data=bytearray(b'\xff'*0x80000);data[0x40000:0x44400]=record()
        (d/'boot-state').write_bytes(data)
        (d/'kernel0').write_bytes(b'\x55'*0x600000)
        (d/'dtb0').write_bytes(b'\x55'*0x60000)
        return d

    def flash(self,d,operation,arg,fault=0,output=False):
        r=subprocess.run([str(self.build/'flash'),operation,str(arg),str(fault)],cwd=d,capture_output=True,text=True)
        return (r.returncode,r.stderr) if output else r.returncode

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

    def test_stock_bootloader_selections_are_validated_and_preserved(self):
        for env_bank in (0,1):
            for uboot_bank in (0,1):
                parts=list(PARTS)
                for start,bank in ((2,env_bank),(4,uboot_bank)):
                    for n in (0,1):
                        parts[start+n]=(*parts[start+n][:3],int(n==bank))
                original=record(parts=parts)
                self.assertTrue(self.layout(b'\xff'*0x4400,original))
                d=self.flash_directory()
                data=bytearray((d/'boot-state').read_bytes());data[0x40000:0x44400]=original
                (d/'boot-state').write_bytes(data)
                self.assertEqual(self.flash(d,'select',0),0)
                after=(d/'boot-state').read_bytes()
                self.assertEqual(after[1024+2*128:1024+6*128],original[1024+2*128:1024+6*128])
                self.assertEqual(self.flash(d,'select',1),0)
                final=(d/'boot-state').read_bytes()
                self.assertEqual(final[0x40000+1024+2*128:0x40000+1024+6*128],original[1024+2*128:1024+6*128])

    def test_torn_gpt_keeps_previous_record_and_can_retry(self):
        # 1: torn write, 3: wrong byte read back, 4: erase fails,
        # 5: the new record reads back with an uncorrectable ECC error.
        for fault in (1,3,4,5):
            with self.subTest(fault=fault):
                d=self.flash_directory();before=(d/'boot-state').read_bytes()
                self.assertNotEqual(self.flash(d,'select',0,fault),0)
                after=(d/'boot-state').read_bytes()
                self.assertEqual(after[0x40000:],before[0x40000:])
                # A failed write is erased again: SPL then only sees a bad CRC.
                self.assertEqual(after[:0x4800],b'\xff'*0x4800)
                self.assertTrue(self.layout(after[:0x4400],after[0x40000:0x44400]))
                self.assertEqual(self.flash(d,'select',0),0)

    def test_gpt_left_unreadable_is_reported(self):
        d=self.flash_directory();before=(d/'boot-state').read_bytes()
        rc,err=self.flash(d,'select',0,6,output=True)
        self.assertNotEqual(rc,0)
        self.assertIn('keep the unit powered',err)
        self.assertEqual((d/'boot-state').read_bytes()[0x40000:],before[0x40000:])

    def test_nand_bad_block_skipping_readback_and_errors(self):
        d=self.flash_directory();image=bytes(range(256))*1200;(d/'image').write_bytes(image)
        self.assertEqual(self.flash(d,'write','image',2),0)
        data=(d/'kernel0').read_bytes()
        self.assertEqual(data[:0x20000],image[:0x20000])
        self.assertEqual(data[0x20000:0x40000],b'\x55'*0x20000)
        self.assertEqual(data[0x40000:0x40000+len(image)-0x20000],image[0x20000:])
        self.assertEqual(self.flash(d,'compare','image',2),0)
        for fault in (1,3,4,7):
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
        code = bytes(mod['GUARD_BYTES'] - 4) + mod['branch'](0)
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

    def test_guard_assembles_to_the_checked_size(self):
        gcc, objcopy = shutil.which('aarch64-linux-gnu-gcc'), shutil.which('aarch64-linux-gnu-objcopy')
        if not gcc or not objcopy: self.skipTest('no aarch64 cross toolchain')
        mod = runpy.run_path(str(ROOT / 'boot/p1-bootguard.py'))
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([gcc, '-c', str(ROOT / 'boot/p1-bootguard.S'), '-o', f'{d}/g.o'], check=True)
            subprocess.run([objcopy, '-O', 'binary', '-j', '.text', f'{d}/g.o', f'{d}/g.bin'], check=True)
            code = Path(f'{d}/g.bin').read_bytes()
        self.assertEqual(len(code), mod['GUARD_BYTES'])
        self.assertEqual(code[-4:], mod['branch'](0))

    def test_crash_restarts_boot_fpvos_until_the_last_try(self):
        # Runs the guard itself under qemu-aarch64, with its two register pages
        # mapped at their physical addresses (the test build returns at the end).
        gcc, qemu = shutil.which('aarch64-linux-gnu-gcc'), shutil.which('qemu-aarch64')
        if not gcc or not qemu: self.skipTest('no aarch64 cross toolchain or qemu-aarch64')
        harness = r'''
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
void p1_bootguard(void);
static volatile uint32_t *page(uintptr_t at)
{
    void *p = mmap((void *)at, 4096, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    if (p != (void *)at) exit(2);
    return p;
}
int main(int argc, char **argv)
{
    volatile uint32_t *scratch = page(0x0a106000) + 0x138 / 4, *wdt = page(0x01600000);
    (void)argc;
    *scratch = strtoul(argv[1], NULL, 0);
    p1_bootguard();
    printf("%#x %#x %#x %#x\n", *scratch, wdt[0], wdt[1], wdt[3]);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as d:
            Path(f'{d}/h.c').write_text(harness)
            subprocess.run([gcc, '-static', '-O1', '-DP1_BOOTGUARD_TEST', f'{d}/h.c',
                            str(ROOT / 'boot/p1-bootguard.S'), '-o', f'{d}/h'], check=True)
            def boot(scratch):
                out = subprocess.run([qemu, f'{d}/h', hex(scratch)], capture_output=True,
                                     text=True, check=True).stdout.split()
                value, enable, top, _ = (int(x, 16) for x in out)
                self.assertEqual((enable, top), (1, 0xff))  # watchdog armed every time
                return value
            # Power-up, then two panics/hangs in a row: fpvOS again, bit 0 clear.
            self.assertEqual(boot(0), 0x102)
            self.assertEqual(boot(0x102), 0x202)
            # The third reset in a row asks the SPL for the USB downloader.
            self.assertEqual(boot(0x202), 3)
            self.assertEqual(boot(0xf02), 3)
            # syscon-reboot-mode's normal restart (2) and a power cycle (0) start over.
            self.assertEqual(boot(2), 0x102)

if __name__=='__main__': unittest.main()
