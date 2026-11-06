"""Private camera protocol validation and live AWB lock/resume with fake ISP I/O."""
from pathlib import Path
import os
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest

PACKAGE = Path(__file__).resolve().parents[1]

class Controls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        (cls.root / 'check.c').write_text(r'''
#include "control.h"
#include <assert.h>
#include <unistd.h>
int main(void) {
 struct camera_request r;
 assert(!camera_parse("SET -10",&r) && camera_ev_valid(&r));
 assert(camera_ev_luma(32,10)==16 && camera_ev_luma(32,-10)==64);
 assert(camera_ev_luma(32,0)==32);
 assert(!camera_parse("SET 11",&r) && !camera_ev_valid(&r));
 assert(!camera_parse("SET -1 313 807",&r) && camera_wb_valid(&r));
 assert(!camera_parse("SET 0 313 807",&r) && !camera_wb_valid(&r));
 assert(!camera_parse("SET -1 127 807",&r) && !camera_wb_valid(&r));
 assert(!camera_parse("SET 5200",&r) && !camera_wb_valid(&r));
 assert(camera_parse("SET 9999999999999999999999999",&r));
 assert(camera_parse("SET 1junk",&r)); assert(camera_parse("SET ",&r));
 int s[2];assert(!socketpair(AF_UNIX,SOCK_SEQPACKET,0,s));
 assert(!camera_receive(s[0],&r));
 assert(send(s[1],"SET 0\0bad",9,0)==9);assert(!camera_receive(s[0],&r));
 char reply[64];assert(recv(s[1],reply,sizeof(reply),0)>0 && !memcmp(reply,"ERR",3));
 char large[100];memset(large,'1',sizeof(large));
 assert(send(s[1],large,sizeof(large),0)==sizeof(large));assert(!camera_receive(s[0],&r));
 assert(recv(s[1],reply,sizeof(reply),0)>0 && !memcmp(reply,"ERR",3));
 close(s[1]);assert(camera_receive(s[0],&r)<0);close(s[0]);
}
''')
        subprocess.run(['cc','-Wall','-Wextra','-Werror','-I',str(PACKAGE),str(cls.root/'check.c'),'-lm','-o',str(cls.root/'check')],check=True)
        (cls.root / 'io.c').write_text(r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
FILE *__real_fopen(const char *,const char *);
FILE *__wrap_fopen(const char *p,const char *mode) {
 if(!strcmp(p,"/sys/kernel/debug/ar-isp/stats_raw"))p=getenv("TEST_STATS");
 if(!strcmp(p,"/sys/kernel/debug/ar-isp/white_balance"))p=getenv("TEST_WB");
 return __real_fopen(p,mode);
}
''')
        subprocess.run(['cc','-Wall','-Wextra','-Werror',str(PACKAGE/'awbd.c'),str(PACKAGE/'awb.c'),str(cls.root/'io.c'),'-Wl,--wrap=fopen','-lm','-o',str(cls.root/'awbd')],check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_protocol(self):
        subprocess.run([str(self.root/'check')],check=True)

    def test_lock_resume_restore_and_reject(self):
        stats = bytearray(4+36*512+4096+4)
        for block in range(36):
            for cell in range(16):
                for channel,value in enumerate((60,40,24,60)):
                    offset=4+block*512+cell*16+channel*4
                    struct.pack_into('<I',stats,offset,100)
                    struct.pack_into('<I',stats,offset+256,value*100)
        stop=threading.Event()
        def feed():
            seq=0
            while not stop.is_set():
                seq+=1
                struct.pack_into('<I',stats,0,seq)
                struct.pack_into('<I',stats,len(stats)-4,seq)
                (self.root/'stats.next').write_bytes(stats)
                os.replace(self.root/'stats.next',self.root/'stats')
                stop.wait(.03)
        thread=threading.Thread(target=feed);thread.start()
        parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
        parent.settimeout(2)
        env=dict(os.environ,TEST_STATS=str(self.root/'stats'),TEST_WB=str(self.root/'wb'))
        proc=subprocess.Popen([str(self.root/'awbd'),'grbg','313','807','--control-fd',str(child.fileno())],pass_fds=[child.fileno()],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        child.close()
        def command(value):
            parent.send(value.encode());return parent.recv(64).decode().split()
        try:
            time.sleep(.3)
            locked=command('SET -1')
            self.assertEqual(locked[:2],['OK','-1'])
            gains=tuple(map(int,locked[2:]))
            packed=int((self.root/'wb').read_text())
            self.assertEqual(packed,gains[0]*65536+gains[1])
            time.sleep(.4)
            self.assertEqual(int((self.root/'wb').read_text()),packed)
            self.assertEqual(command('SET 5200')[0],'ERR')
            self.assertEqual(int((self.root/'wb').read_text()),packed)
            self.assertEqual(command('SET -1 400 700'),['OK','-1','400','700'])
            self.assertEqual(command('SET 0')[:2],['OK','0'])
            time.sleep(.4)
            self.assertNotEqual(int((self.root/'wb').read_text()),400*65536+700)
            parent.close();self.assertEqual(proc.wait(timeout=2),0)
        finally:
            parent.close();stop.set();thread.join()
            if proc.poll() is None:proc.terminate();proc.wait(timeout=2)

if __name__=='__main__':unittest.main()
