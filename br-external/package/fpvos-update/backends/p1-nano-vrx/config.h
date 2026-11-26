/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_P1_CONFIG_H
#define FPVOS_P1_CONFIG_H
/* Keep whichever matched env/U-Boot pair the unit already uses. */
#define P1_BOOT_BANK -1
#define P1_MODEL "BETAFPV P1 Nano VRX (AR9311)"
#define P1_COMPATIBLE "betafpv,p1-nano-vrx"
#define P1_KERNEL_NAME "fpvOS P1 Nano VRX recovery"
#define P1_ROOT_LIMIT 0x1000000
/* Initial installation is from independently RAM-booted recovery. */
#define P1_STOCK_BOOTSTRAP 0
#endif
