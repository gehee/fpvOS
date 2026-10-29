# SPDX-License-Identifier: GPL-2.0-or-later
"""A synthetic second board proves the framework does not depend on AR9311."""
import copy
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import zlib
from test_update import BOARD, CLIENT, PACKAGE, PKG, SRC
from boards import get_profile, read_profile


class Profiles(unittest.TestCase):
    def test_gnd485_and_legacy_board_name_produce_identical_bundles(self):
        canonical = get_profile('ascent-gnd485')
        self.assertEqual(canonical, get_profile('ar9311'))
        self.assertEqual(canonical['board_id'], 485)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in canonical['names']:
                (root / name).write_bytes(b'profile compatibility fixture')
            bundles = []
            for name in ('ascent-gnd485', 'ar9311'):
                output = root / (name + '.fwu')
                subprocess.run(['python3', str(PKG.parents[2] / 'tools/fpvos-update/package.py'),
                                '--board', name, str(root), str(output)], check=True,
                               capture_output=True)
                bundles.append(output.read_bytes())
            self.assertEqual(*bundles)

    def test_second_board_bundle_and_image_backend(self):
        profile = dict(board_id=902, hardware='Test board', usb_identity=['1234','5678','test-board'],
                       names=['boot.bin','system.bin'], limits=[8,8], counts=[2,0],
                       bundle_limits=[528,512], restore_sources=[])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = root/'profile.json'
            definition.write_text(json.dumps(profile))
            profile = read_profile(definition)
            subprocess.run(['python3', str(PKG/'generate-profile.py'), str(definition), str(root/'profile.c')], check=True)
            (root/'images.c').write_text('#include "board.h"\n#include <string.h>\nint fpvos_board_image_valid(unsigned i, const unsigned char *b, size_t n, unsigned kind) { return i < 2 && kind == 0 && n == 4 && !memcmp(b,"RAW!",4); }\n')
            subprocess.run(['cc','-Wall','-Wextra','-Werror','-O2','-I'+str(SRC),str(SRC/'verify.c'),str(root/'profile.c'),str(root/'images.c'),'-o',str(root/'verify')], check=True)
            for name in profile['names']:
                (root/name).write_bytes(b'RAW!')
            bundle = PACKAGE.build(root, profile)
            def verify(data):
                (root/'bundle').write_bytes(data)
                with tempfile.TemporaryDirectory(dir=root) as output:
                    return subprocess.run([str(root/'verify'),str(root/'bundle'),output],capture_output=True).returncode
            self.assertEqual(verify(bundle),0)
            wrong = bytearray(bundle)
            struct.pack_into('<I',wrong,12,485)
            struct.pack_into('<I',wrong,508,0)
            struct.pack_into('<I',wrong,508,zlib.crc32(wrong[:512]))
            self.assertNotEqual(verify(wrong),0)
            # Integrity alone must not replace the board's image policy.
            (root/'boot.bin').write_bytes(b'BAD!')
            self.assertNotEqual(verify(PACKAGE.build(root,profile)),0)
            with self.assertRaisesRegex(ValueError,'does not support'):
                PACKAGE.build(root,profile,vendor_restore=True)
            profile['bundle_limits'][0]=519
            with self.assertRaisesRegex(ValueError,'storage capacity'):
                PACKAGE.build(root,profile)

    def test_profile_rejects_unknown_board_and_unsafe_components(self):
        for name in ('missing','../ar9311'):
            with self.assertRaises(ValueError): get_profile(name)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'profile.json'
            bad=copy.deepcopy(BOARD);bad['names'][0]='../kernel.img'
            p.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError,'component name'): read_profile(p)

    def test_host_can_upload_to_legacy_receiver(self):
        class Legacy(CLIENT.Client):
            def info(self):
                return dict(device=BOARD['legacy_service'],chunk_limit=1024)
            def ack(self,command,data=b''):
                if command==0x73:
                    self.destination=struct.unpack('<64sii128s128s',data)[3].split(b'\0')[0]
                    self.total=struct.unpack_from('<I',data,64)[0]
                return struct.pack('<IIIi64s',len(data),getattr(self,'total',0),getattr(self,'total',0),0,b'OK')
            def exchange(self,command,data=b''):
                return struct.pack('<Ii64s',90,2,b'verified')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bundle';p.write_bytes(b'test payload')
            client=Legacy(-1,BOARD)
            result=client.verify(p,enter_clean=False)
            self.assertFalse(result['installed'])
            self.assertEqual(client.destination,b'/tmp/pc/fpvos-ar9311.verify')
