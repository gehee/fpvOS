/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_P1_CONFIG_H
#define FPVOS_P1_CONFIG_H
/* P1 units use either matched env/U-Boot pair; preserve the existing choice. */
#define P1_BOOT_BANK -1
#define P1_MODEL "BETAFPV P1 Air (AR9311) source bring-up"
#define P1_COMPATIBLE "betafpv,p1-air"
#define P1_KERNEL_NAME "fpvOS P1 recovery"
#define P1_ROOT_LIMIT 0x800000
#define P1_STOCK_BOOTSTRAP 1
#endif
