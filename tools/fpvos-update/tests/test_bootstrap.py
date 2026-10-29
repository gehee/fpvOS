# SPDX-License-Identifier: GPL-2.0-or-later
import importlib.util
import os
from pathlib import Path
import struct
import shutil
from types import SimpleNamespace
import subprocess
import sys
import tempfile
import unittest
import zlib
import test_update as base

PKG, SRC = base.PKG, base.SRC
BACKEND = PKG / 'backends/ascent-gnd485'
sys.path.insert(0, str(PKG))
spec = importlib.util.spec_from_file_location('bootstrap', PKG / 'embed-bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def compile_unified(destination):
    subprocess.run(['python3', str(PKG/'generate-profile.py'), str(BACKEND/'profile.json'), str(destination/'profile.c')], check=True)
    for source, name in ((SRC/'receiver.c', 'receiver'), (SRC/'verify.c', 'verify'), (BACKEND/'nand.c', 'nand')):
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', '-I'+str(SRC),
                        f'-DCLEAN_BOOT_MARKER="{destination / "clean-boot"}"', '-Dmain=fpvos_'+name+'_main', '-c', str(source), '-o', str(destination/(name+'.o'))], check=True)
    busybox = destination/'busybox.fixture'; busybox.write_bytes(BootstrapArtifact.elf())
    bootstrap.build(busybox, BACKEND, destination/'resources.c')
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', '-I'+str(SRC), str(SRC/'main.c'),
                    str(BACKEND/'bootstrap.c'), str(destination/'resources.c'),
                    *[str(destination/(n+'.o')) for n in ('receiver', 'verify', 'nand')],
                    str(destination/'profile.c'), str(BACKEND/'images.c'), '-o', str(destination/'fpvos-update')], check=True)
    # Existing protocol/image tests now run through the multicall entry points.
    for alias, command in (('receiver', 'receive'), ('verify', 'verify')):
        p = destination/alias
        p.write_text(f'#!/bin/sh\nexec "{destination}/fpvos-update" {command} "$@"\n')
        p.chmod(0o755)


class UnifiedUpdater(base.Tests):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.bin = Path(cls.build.name)
        compile_unified(cls.bin)

    def test_bootstrap_rejects_unrecognized_runtime_without_staging(self):
        for args in (['bootstrap'], ['bootstrap', '--ram', '/tmp/fpvos-bootstrap.untrusted']):
            result = subprocess.run([str(self.bin/'fpvos-update'), *args], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'supported stock Gnd485 runtime', result.stderr)


class BootstrapArtifact(unittest.TestCase):
    def test_static_validation_rejects_wrong_arch_and_dynamic(self):
        for data in (b'not ELF', bytes(64)):
            with self.assertRaises(ValueError): bootstrap.static_aarch64(data)
        data = self.elf()
        bootstrap.static_aarch64(data)
        for kind in (2, 3):
            bad = bytearray(data); struct.pack_into('<I', bad, 64, kind)
            with self.assertRaisesRegex(ValueError, 'statically'): bootstrap.static_aarch64(bad)

    @staticmethod
    def elf():
        b = bytearray(120); b[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', b, 18, 183); struct.pack_into('<Q', b, 32, 64)
        struct.pack_into('<HH', b, 54, 56, 1); struct.pack_into('<I', b, 64, 1)
        return bytes(b)

    def test_reproducible_embedded_resources_and_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); busybox = root/'busybox'; busybox.write_bytes(self.elf())
            first, second = root/'first.c', root/'second.c'
            bootstrap.build(busybox, BACKEND, first); bootstrap.build(busybox, BACKEND, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            driver = root/'extract.c'
            driver.write_text('int fpvos_stock_runtime_valid(void){return 0;}\nint fpvos_bootstrap_extract(const char *);\nint main(int argc,char **argv){return argc != 2 || fpvos_bootstrap_extract(argv[1]);}\n')
            subprocess.run(['cc','-Wall','-Wextra','-Werror','-O2','-I'+str(SRC),str(driver),str(BACKEND/'bootstrap.c'),str(first),'-o',str(root/'extract')],check=True)
            output = root/'ram'; output.mkdir(mode=0o700)
            subprocess.run([str(root/'extract'),str(output)],check=True)
            self.assertEqual((output/'root/bin/busybox').read_bytes(), self.elf())
            self.assertEqual((output/'prepare.sh').read_bytes(), (BACKEND/'bootstrap-ram.sh').read_bytes())
            self.assertEqual((output/'root/usr/libexec/fpvos-update-backend').read_bytes(), (BACKEND/'update-helper').read_bytes())
            self.assertEqual(os.readlink(output/'root/bin/sh'), 'busybox')
            self.assertEqual(os.readlink(output/'root/usr/libexec/fpvos-update-verify'), '../sbin/fpvos-update')
            # Refuse a preexisting extraction tree; never overwrite its files.
            self.assertNotEqual(subprocess.run([str(root/'extract'),str(output)]).returncode, 0)

    def test_launcher_is_valid_shell_and_does_not_run_from_arbitrary_context(self):
        script = BACKEND/'bootstrap.sh'
        subprocess.run(['sh', '-n', str(script)], check=True)
        # This exits before any staging, mount, USB or NAND action.
        result = subprocess.run(['sh', str(script)], env={'PATH': '/usr/bin:/bin'}, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        subprocess.run(['sh', '-n', str(BACKEND/'bootstrap-ram.sh')], check=True)

    def test_receiver_handoff_replaces_host_path_after_entering_ram_chroot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # The wrapper stands in for the namespace change only. Execute the
            # real shell handoff with a host-side PATH containing no md5sum.
            (root/'chroot').write_text('#!/bin/sh\nshift\nexec "$@"\n')
            (root/'chroot').chmod(0o755)
            command = (BACKEND/'bootstrap-ram.sh').read_text().splitlines()[-1]
            command = command.replace('exec /usr/sbin/fpvos-update receive /dev/ttyGS0 /run/fpvos-update /usr/libexec/fpvos-update-backend',
                                      'command -v md5sum; printf "%s\\n" "$PATH"')
            result = subprocess.run(['/bin/sh', '-c', command], env={'PATH':tmp, 'root':'fixture'}, capture_output=True, check=True)
            self.assertIn(b'/bin/md5sum\n', result.stdout)
            self.assertTrue(result.stdout.endswith(b'/bin:/usr/sbin:/usr/libexec\n'))


class RuntimePreflight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(); cls.binary = Path(cls.build.name)/'runtime'
        base.compile_framework(Path(cls.build.name))
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', '-DWORK="work"', '-DROOT_IMAGES="root"',
                        f'-DVERIFY_PROGRAM="{Path(cls.build.name) / "verify"}"', str(BACKEND/'nand.c'),
                        str(Path(__file__).with_name('runtime_sim.c')),
                         *['-Wl,--wrap='+s for s in ('open', '__open_2', 'fopen', 'opendir', 'uname', 'geteuid', 'ioctl')], '-o', str(cls.binary)], check=True)
        kernel_patch = (PKG.parents[1]/'board/ascent-gnd485/linux-patches/0009-mtd-ar9311-bank-aware-partitions.patch').read_text()
        added = kernel_patch.split('+++ b/drivers/mtd/parsers/ofpart_ar9311.h\n', 1)[1].split('\n', 1)[1]
        header = '\n'.join(line[1:] for line in added.splitlines() if line.startswith('+'))+'\n'
        header = header.replace('#include <linux/string.h>', '#include <string.h>')
        dest = Path(cls.build.name)
        (dest/'ofpart_ar9311.h').write_text(header)
        (dest/'fpvos_ar9311_layout.h').write_bytes((BACKEND/'layout.h').read_bytes())
        cls.kernel = dest/'kernel-partitions'
        subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-O2', '-I'+str(dest),
                        str(Path(__file__).with_name('kernel_partition_sim.c')), '-o', str(cls.kernel)], check=True)

    @classmethod
    def tearDownClass(cls): cls.build.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        for name in ('proc/device-tree', 'sys/class/mtd', 'sys/class/ubi', 'dev', 'etc'):
            (self.root/name).mkdir(parents=True, exist_ok=True)
        (self.root/'proc/device-tree/model').write_text('Artosyn, Proxima Development Board\0')
        (self.root/'etc/app.version').write_text('BOARD_TYPE=Gnd485\n')
        # Read the exact tested map from the captured stock startup contract.
        prefix = ('mtdparts=spi32766.1:256k@0(spl0),256k(spl1),256k(spl2),256k(spl3),256k(gpt0),256k(gpt1),'
                  '512K(vendor),6M(factory),512K(bl31),384K(env0),384K(env1),1M(uboot0),1M(uboot1),'
                  '6M(kernel),384K(dtb),21M(userapp0),21M(userapp1)')
        (self.root/'proc/cmdline').write_text('console=ttyS0 '+prefix+',22M(usr_data0),22M(usr_data1),22M(fpv_data)')
        for number, name, size in ((0, 'spi32766.1', 0x8000000), (14, 'kernel', 0x600000), (15, 'dtb', 0x60000), (17, 'userapp1', 0x1500000)):
            d = self.root/f'sys/class/mtd/mtd{number}'; d.mkdir(); (d/'name').write_text(name+'\n')
            with (self.root/f'dev/mtd{number}').open('wb') as f: f.truncate(size)
        raw = bytearray(b'\xff'*0xb40000); entries = bytearray(16384)
        for i, (name, start, size) in enumerate((('kernel',0xb40000,0x600000), ('dtb',0x1140000,0x60000),
                                                ('userapp0',0x11a0000,0x1500000), ('userapp1',0x26a0000,0x1500000))):
            struct.pack_into('<QQQ', entries, i*128+32, start//512, (start+size)//512-1, (1<<47) if i != 3 else 0)
            entries[i*128+56:i*128+56+len(name)*2] = name.encode('utf-16le')
        h = bytearray(512); h[:8] = b'EFI PART'; struct.pack_into('<II',h,8,0x10000,92)
        struct.pack_into('<QQQQ',h,24,1,0x3f7ff,0xc00,0x3f7de)
        struct.pack_into('<QIII',h,72,2,128,128,zlib.crc32(entries)); struct.pack_into('<I',h,16,zlib.crc32(h[:92]))
        raw[0x100200:0x100400] = h; raw[0x100400:0x104400] = entries
        with (self.root/'dev/mtd0').open('r+b') as f: f.write(raw)

    def tearDown(self): self.temp.cleanup()

    def run_preflight(self, success=True, command='preflight', **env):
        result = subprocess.run([str(self.binary),command], cwd=self.root, env={**os.environ, **env}, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        return result

    def test_stock_readonly_preflight_and_unknown_kernel_rejection(self):
        self.assertIn(b'stock NAND', self.run_preflight().stdout)
        self.run_preflight(False, TEST_RELEASE='6.18.36')
        self.run_preflight(False, TEST_BADBLOCK='1')
        for command in ('boot','clean'): self.run_preflight(False, command=command)

    def test_changed_map_board_geometry_and_attached_ubi_rejected(self):
        p = self.root/'etc/app.version'; p.write_text('BOARD_TYPE=Gnd486\n'); self.run_preflight(False)
        p.write_text('BOARD_TYPE=Gnd485\n')
        cmd = self.root/'proc/cmdline'; old = cmd.read_text(); cmd.write_text(old.replace('6M(kernel)','5M(kernel)')); self.run_preflight(False); cmd.write_text(old)
        ubi = self.root/'sys/class/ubi/ubi0'; ubi.mkdir(); (ubi/'mtd_num').write_text('17\n'); self.run_preflight(False)
        (ubi/'mtd_num').write_text('0\n'); self.run_preflight(False)

    def test_native_fixed_partitions_require_exact_offsets(self):
        (self.root/'proc/device-tree/model').write_text('Caddx Ascent Gnd485 (AR9311)\0')
        (self.root/'sys/class/mtd/mtd0/name').write_text('boot-protected\n')
        with (self.root/'dev/mtd0').open('r+b') as f: f.truncate(0xb40000)
        (self.root/'sys/class/mtd/mtd17/name').write_text('fpvos\n')
        self.run_preflight(False)
        for number, offset in ((0,0),(14,0xb40000),(15,0x1140000),(17,0x26a0000)):
            (self.root/f'sys/class/mtd/mtd{number}/offset').write_text(hex(offset)+'\n')
        self.assertIn(b'fpvOS NAND', self.run_preflight().stdout)
        (self.root/'sys/class/mtd/mtd17/offset').write_text('0\n'); self.run_preflight(False)

    def test_boot_checks_used_blocks_but_ignores_unused_bad_tail(self):
        (self.root/'proc/device-tree/model').write_text('Caddx Ascent Gnd485 (AR9311)\0')
        (self.root/'sys/class/mtd/mtd0/name').write_text('boot-protected\n')
        with (self.root/'dev/mtd0').open('r+b') as f: f.truncate(0xb40000)
        (self.root/'sys/class/mtd/mtd17/name').write_text('fpvos\n')
        for number, offset in ((0,0),(14,0xb40000),(15,0x1140000),(17,0x26a0000)):
            (self.root/f'sys/class/mtd/mtd{number}/offset').write_text(hex(offset)+'\n')
        bundle = base.Tests.fixture(SimpleNamespace(dir=self.root))
        for number, name in ((14, 'kernel.img'), (15, 'ascent-gnd485.dtb')):
            with (self.root/f'dev/mtd{number}').open('r+b') as f:
                f.write((self.root/'images'/name).read_bytes())
        record = bytearray(b'\xff'*2048); record[:8] = b'FPVOCTL1'
        struct.pack_into('<QII', record, 8, 1, 0, 0)
        struct.pack_into('<I', record, 20, zlib.crc32(record))
        with (self.root/'dev/mtd17').open('r+b') as f:
            f.write(record); f.seek(0x40000); f.write(bundle)
        for mtd, offset, success in ((17,0x14e0000,True), (14,0x5e0000,True),
                                     (0,0,True), (17,0x40000,False), (14,0,False),
                                     (17,0,False), (0,0x100000,False)):
            with self.subTest(mtd=mtd, offset=offset):
                self.run_preflight(success, command='boot', TEST_BOOT='1',
                                   TEST_BAD_MTD=str(mtd), TEST_BAD_OFFSET=hex(offset))
                if success:
                    self.assertEqual((self.root/'root/rootfs.cpio.uboot').read_bytes(),
                                     (self.root/'images/rootfs.cpio.uboot').read_bytes())
                shutil.rmtree(self.root/'root', ignore_errors=True)
                (self.root/'work/boot.fwu').unlink(missing_ok=True)
        # Installation preflight still refuses the same unused bad block.
        self.run_preflight(False, TEST_BAD_MTD='17', TEST_BAD_OFFSET='0x14e0000')

    def test_preserved_stock_root_may_be_attached_but_geometry_must_match(self):
        d = self.root/'sys/class/mtd/mtd16'; d.mkdir(); (d/'name').write_text('userapp0\n')
        ubi = self.root/'sys/class/ubi/ubi0'; ubi.mkdir(); (ubi/'mtd_num').write_text('16\n')
        self.run_preflight()
        factory = self.root/'sys/class/mtd/mtd8'; factory.mkdir(); (factory/'name').write_text('factory\n')
        data_ubi = self.root/'sys/class/ubi/ubi10'; data_ubi.mkdir(); (data_ubi/'mtd_num').write_text('8\n')
        self.run_preflight()
        with (self.root/'dev/mtd15').open('r+b') as f: f.truncate(4096)
        self.run_preflight(False)

    def select_stock_bank(self, bank):
        p = self.root/'dev/mtd0'
        raw = bytearray(p.read_bytes())
        for index in (2, 3):
            struct.pack_into('<Q', raw, 0x100400+index*128+48, (1 << 47) if index == 2+bank else 0)
        struct.pack_into('<I', raw, 0x100258, zlib.crc32(raw[0x100400:0x104400]))
        struct.pack_into('<I', raw, 0x100210, 0)
        struct.pack_into('<I', raw, 0x100210, zlib.crc32(raw[0x100200:0x10025c]))
        p.write_bytes(raw)

    def test_stock_bank_one_preserved_and_bank_zero_destination_must_be_detached(self):
        self.select_stock_bank(1)
        d = self.root/'sys/class/mtd/mtd16'; d.mkdir(); (d/'name').write_text('userapp0\n')
        with (self.root/'dev/mtd16').open('wb') as f: f.truncate(0x1500000)
        ubi = self.root/'sys/class/ubi/ubi0'; ubi.mkdir(); (ubi/'mtd_num').write_text('17\n')
        before = (self.root/'dev/mtd0').read_bytes()
        self.assertIn(b'stock=userapp1 fpvOS=userapp0', self.run_preflight().stdout)
        self.assertEqual((self.root/'dev/mtd0').read_bytes(), before)
        (ubi/'mtd_num').write_text('16\n')
        self.assertIn(b'unsafe attached UBI', self.run_preflight(False).stderr)

    def test_native_bank_one_requires_kernel_partition_mapping_to_agree(self):
        self.select_stock_bank(1)
        (self.root/'proc/device-tree/model').write_text('Caddx Ascent Gnd485 (AR9311)\0')
        (self.root/'sys/class/mtd/mtd0/name').write_text('boot-protected\n')
        with (self.root/'dev/mtd0').open('r+b') as f: f.truncate(0xb40000)
        (self.root/'sys/class/mtd/mtd17/name').write_text('fpvos\n')
        for number, offset in ((0,0),(14,0xb40000),(15,0x1140000),(17,0x26a0000)):
            (self.root/f'sys/class/mtd/mtd{number}/offset').write_text(hex(offset)+'\n')
        self.run_preflight(False)  # The old fixed-bank DT must not be accepted.
        (self.root/'sys/class/mtd/mtd17/offset').write_text('0x11a0000\n')
        self.assertIn(b'stock=userapp1 fpvOS=userapp0', self.run_preflight().stdout)

    def test_kernel_maps_only_inactive_bank_writable_and_rejects_bad_metadata(self):
        for bank, expected in ((0, b'vendor=11a0000 fpvos=26a0000'), (1, b'vendor=26a0000 fpvos=11a0000')):
            self.select_stock_bank(bank)
            result = subprocess.run([str(self.kernel)], cwd=self.root, capture_output=True, check=True)
            self.assertIn(expected, result.stdout)
        for env in ({'TEST_BAD_MAP':'1'}, {'TEST_READ_FAIL':'1'}):
            result = subprocess.run([str(self.kernel)], cwd=self.root, env={**os.environ, **env}, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        p = self.root/'dev/mtd0'
        raw = bytearray(p.read_bytes()); raw[0x100210] ^= 1; p.write_bytes(raw)
        result = subprocess.run([str(self.kernel)], cwd=self.root, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


class MountPolicy(unittest.TestCase):
    def test_chroot_mount_check_uses_host_view_and_fails_if_unavailable(self):
        # Execute the actual helper function against separate host/chroot proc
        # fixtures. A virtual-only self view must not hide a dirty host mount.
        helper = (BACKEND/'update-helper').read_text()
        function = helper.split('check_mounts() {', 1)[1].split('\n}\n', 1)[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'1').mkdir()
            (root/'mounts').write_text('tmpfs / tmpfs rw 0 0\nproc /proc proc rw 0 0\n')
            host = root/'1/mounts'
            stock_root = '/dev/root / squashfs ro,relatime 0 0\n'
            function = function.replace('/proc/', str(root)+'/')
            command = 'check_mounts() {'+function+'\n}\ncheck_mounts'
            def check(stock, allowed):
                r = subprocess.run(['sh', '-c', command], env={**os.environ, 'stock':str(stock)}, capture_output=True)
                self.assertEqual(r.returncode == 0, allowed, r.stderr)
            for mount in ('/dev/ubi10_0 /factory ubifs rw 0 0\n',
                          '/dev/ubi18_0 /usrdata ubifs rw 0 0\n'):
                host.write_text(stock_root+mount); check(1, False); check(0, True)
            host.write_text(stock_root); check(1, True)
            host.write_text(''); check(1, False)
            host.unlink(); check(1, False)

    def test_install_helper_delegates_verification_but_keeps_mount_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'proc/device-tree').mkdir(parents=True)
            (root/'proc/device-tree/model').write_bytes(b'Caddx Ascent Gnd485 (AR9311)\0')
            (root/'proc/mounts').write_text('tmpfs / tmpfs rw 0 0\n')
            (root/'work').mkdir(); (root/'work/clean').touch()
            for name in ('nand', 'verify'):
                tool = root/name
                tool.write_text(f'#!/bin/sh\necho {name} >> "{root}/calls"\n')
                tool.chmod(0o755)
            script = (BACKEND/'update-helper').read_text()
            script = script.replace('#!/bin/sh', '#!/bin/sh\nid() { echo 0; }')
            script = script.replace('/proc/', str(root/'proc')+'/')
            script = script.replace('/run/fpvos-update', str(root/'work'))
            script = script.replace('/usr/sbin/ar9311-nandctl', str(root/'nand'))
            script = script.replace('/usr/libexec/fpvos-update-verify', str(root/'verify'))
            helper = root/'helper'; helper.write_text(script)
            subprocess.run(['sh',str(helper),'install','fixture.fwu'],check=True)
            self.assertEqual((root/'calls').read_text(), 'nand\n')
            subprocess.run(['sh',str(helper),'verify','fixture.fwu'],check=True)
            self.assertEqual((root/'calls').read_text(), 'nand\nverify\n')
            with (root/'proc/mounts').open('a') as f: f.write('/dev/ubi0_0 /data ubifs rw 0 0\n')
            result = subprocess.run(['sh',str(helper),'install','fixture.fwu'])
            self.assertNotEqual(result.returncode,0)
            self.assertEqual((root/'calls').read_text(), 'nand\nverify\n')

    def test_only_preserved_readonly_stock_root_and_virtual_mounts_are_allowed(self):
        helper = (BACKEND/'update-helper').read_text()
        program = helper.split('awk -v stock="$stock" \x27', 1)[1].split("' ", 1)[0]
        virtual = 'tmpfs /tmp tmpfs rw 0 0\nproc /proc proc rw 0 0\n'
        for source in ('/dev/root', '/dev/ubiblock0_0'):
            root = f'{source} / squashfs ro,relatime 0 0\n'
            for stock, mounts, allowed in ((1, root+virtual, True), (0, root+virtual, False),
                                           (1, root.replace('ro,','rw,')+virtual, False),
                                           (1, root+virtual+'/dev/ubi10_0 /factory ubifs rw 0 0\n', False),
                                           (0, virtual, True)):
                result = subprocess.run(['awk','-v',f'stock={stock}',program], input=mounts.encode())
                self.assertEqual(result.returncode == 0, allowed)
