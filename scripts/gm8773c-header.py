"""Write panel-gm8773c.h from stock's libpn_gm8773c.so (BETAFPV P1 ground 2.1.4)."""
import hashlib, re, struct, subprocess, sys
lib, out = sys.argv[1], sys.argv[2]
d = open(lib, 'rb').read()
# the bridge's own registers: the (reg, value) pairs of the function at 0xdb0,
# up to its call of the command loop; the one write after it ends the sequence
dis = subprocess.run(['aarch64-linux-gnu-objdump', '-d', '--start-address=0xdb0', '--stop-address=0x1000', lib],
                     capture_output=True, text=True, check=True).stdout
regs, w1, w2, tail = [], None, None, []
looped = False
for line in dis.splitlines():
    m = re.search(r'mov\s+w([12]), #(0x[0-9a-f]+)', line)
    if m:
        v = int(m.group(2), 16) & 0xff
        if m.group(1) == '1': w1 = v
        else: w2 = v
    elif re.search(r'bl\s+a0c ', line):
        (tail if looped else regs).append((w1, w2))
    elif re.search(r'bl\s+d90 ', line):
        looped = True
assert len(regs) == 34 and tail == [(0xff, 0x01)], (len(regs), tail)
T, N, SZ = 0x2058, 204, 2580
cmds = []
for i in range(N):
    e = d[T + i*SZ: T + (i+1)*SZ]
    typ, ed, ee = struct.unpack_from('<III', e, 0)
    ln, fb = e[12], struct.unpack_from('<I', e, 2576)[0]
    if typ == 0x102:                      # a wait, in ms, after the command before it
        assert ln == 1 and cmds
        cmds[-1][3] = e[13]
        continue
    assert (typ, ed, ee, ln, fb) == (0xb, 1, 0, 3, 204), (i, typ, ed, ee, ln, fb)
    assert e[13] in (0x05, 0x15)
    cmds.append([e[13], e[14], e[15], 0])
assert len(cmds) == 202 and cmds[-2][:2] == [0x05, 0x11] and cmds[-1][:2] == [0x05, 0x29]
h = hashlib.sha256(d).hexdigest()
with open(out, 'w') as f:
    f.write(f"""/* SPDX-License-Identifier: GPL-2.0 */
/*
 * What stock writes to the GM8773C on the BETAFPV VR04 HD Pro goggles, read
 * from libpn_gm8773c.so of the P1 ground firmware 2.1.4
 * (sha256 {h}):
 * the bridge's own {len(regs)} registers (the code at 0xdb0), then the {len(cmds)} DSI
 * packets it relays to the panel in low-power mode (the table at .data 0x12058,
 * {N} entries of {SZ} bytes, two of them waits), ending with Sleep-Out and
 * Display-On.
 *
 * Do not hand-edit; regenerate from the library.
 */
#ifndef _PANEL_GM8773C_H
#define _PANEL_GM8773C_H

struct gm8773c_reg {{
	u8 reg;
	u8 val;
}};

/* A DSI short packet: its data type (0x15 with a parameter, 0x05 without),
 * the DCS command, the parameter, and the wait after it in ms.
 */
struct gm8773c_cmd {{
	u8 type;
	u8 cmd;
	u8 param;
	u8 delay;
}};

static const struct gm8773c_reg gm8773c_regs[] = {{
""")
    for r, v in regs: f.write(f"\t{{ 0x{r:02x}, 0x{v:02x} }},\n")
    f.write("};\n\nstatic const struct gm8773c_cmd gm8773c_panel_init[] = {\n")
    for t, c, p, w in cmds: f.write(f"\t{{ 0x{t:02x}, 0x{c:02x}, 0x{p:02x}, {w} }},\n")
    f.write("};\n\n#endif /* _PANEL_GM8773C_H */\n")
print(len(regs), len(cmds), h[:12])
