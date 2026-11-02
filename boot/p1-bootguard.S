/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Runs before the ARM64 primary entry. Leave x0 (DTB) and x18 intact.
 * P1 SPL consumes scratch bits 0/1 to enter U-Boot's USB downloader.
 * A normal Linux restart clears request bit 0 through syscon-reboot-mode; a hang
 * leaves them set. TOP=15 at 24 MHz gives about 89 seconds to adopt WDT.
 */
.section .text
.global p1_bootguard
p1_bootguard:
    mov x9, #0x6138
    movk x9, #0x0a10, lsl #16
    mov w10, #3
    str w10, [x9]
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
    b . /* Replaced with a relative branch back to Image + 4. */
