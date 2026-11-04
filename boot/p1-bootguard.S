/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Runs before the ARM64 primary entry. Leave x0 (DTB) and x18 intact.
 * P1 SPL: scratch bit 0 set makes it clear the word and enter U-Boot's USB
 * downloader (bit 1 selects USB); bit 0 clear boots this kernel again.
 * Bits 8-11 count guarded boots since the last clean restart or power-up: a
 * normal Linux restart writes 2 through syscon-reboot-mode, which clears them,
 * while a panic or hang (emergency restart, watchdog) keeps them. So a crash
 * in flight boots fpvOS again, and only the last of P1_GUARD_TRIES resets in
 * a row requests the downloader. TOP=15 at 24 MHz gives about 89 seconds to
 * adopt WDT.
 */
#define P1_GUARD_TRIES 3
.section .text
.global p1_bootguard
p1_bootguard:
    mov x9, #0x6138
    movk x9, #0x0a10, lsl #16
    ldr w10, [x9]
    ubfx w11, w10, #8, #4
    cmp w11, #(P1_GUARD_TRIES - 1)
    b.hs 1f
    add w11, w11, #1
    lsl w10, w11, #8
    orr w10, w10, #2
    b 2f
1:  mov w10, #3
2:  str w10, [x9]
    dmb sy
    mov x9, #0x01600000
    mov w10, #0xff
    str w10, [x9, #4]
    mov w10, #0x76
    str w10, [x9, #12]
    mov w10, #1
    str w10, [x9]
    dsb sy
    isb
#ifdef P1_BOOTGUARD_TEST
    ret
#else
    b . /* Replaced with a relative branch back to Image + 4. */
#endif
