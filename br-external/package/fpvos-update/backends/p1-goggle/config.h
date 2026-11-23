/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_P1_CONFIG_H
#define FPVOS_P1_CONFIG_H
/* Keep the stock environment/U-Boot pair on bank 0, whichever bank fpvOS
 * takes (nand.c chooses per install). */
#define P1_BOOT_BANK 0
#define P1_MODEL "BETAFPV P1 goggles (AR9311)"
#define P1_COMPATIBLE "betafpv,p1-goggle"
#define P1_KERNEL_NAME "fpvOS P1 goggles recovery"
#define P1_ROOT_LIMIT 0x1000000
/* Initial installation is from independently RAM-booted recovery. */
#define P1_STOCK_BOOTSTRAP 0
#endif
