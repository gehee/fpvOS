/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_P1_CONFIG_H
#define FPVOS_P1_CONFIG_H
/* Keep the running stock bank 0 and its original bootloader selection. */
#define P1_FPVOS_BANK 1
#define P1_STOCK_BANK 0
#define P1_BOOT_BANK 0
#define P1_MODEL "BETAFPV P1 goggles (AR9311)"
#define P1_COMPATIBLE "betafpv,p1-goggle"
#define P1_KERNEL_NAME "fpvOS P1 goggles recovery"
#define P1_ROOT_LIMIT 0x1000000
#define P1_KERNEL_PART "kernel1"
#define P1_KERNEL_OFFSET 0x1040000
#define P1_DTB_PART "dtb1"
#define P1_DTB_OFFSET 0x16a0000
#define P1_ROOT_PART "userapp1"
#define P1_ROOT_OFFSET 0x4400000
/* Initial installation is from independently RAM-booted recovery. */
#define P1_STOCK_BOOTSTRAP 0
#endif
