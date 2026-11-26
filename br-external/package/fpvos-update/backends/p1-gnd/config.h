/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_P1_CONFIG_H
#define FPVOS_P1_CONFIG_H
/* Every BETAFPV P1 ground unit fpvOS has a tree for (stock's common P1_GND
 * firmware): the goggles, the Nano VRX (the VRX's board too) and the goggles
 * Pro, a bundle per unit for its device tree. Keep whichever
 * matched environment/U-Boot pair the unit uses (the goggles on bank 0, the
 * Nano VRX as stock left it); nand.c chooses the bank fpvOS takes. */
#define P1_BOOT_BANK -1
#define P1_MODEL "BETAFPV P1 goggles (AR9311)"
#define P1_MODEL_ALT "BETAFPV P1 Nano VRX (AR9311)"
#define P1_COMPATIBLE "betafpv,p1-goggle"
#define P1_COMPATIBLE_ALT "betafpv,p1-nano-vrx"
#define P1_MODEL_ALT2 "BETAFPV P1 goggles Pro (AR9311)"
#define P1_COMPATIBLE_ALT2 "betafpv,p1-goggle-pro"
/* The tree a stock unit's RAM recovery starts with: any ground unit, none of
 * their screens. It takes any unit's bundle (images.c). */
#define P1_MODEL_ANY "BETAFPV P1 ground unit (AR9311)"
#define P1_COMPATIBLE_ANY "betafpv,p1-gnd"
#define P1_KERNEL_NAME "fpvOS P1 ground recovery"
#define P1_ROOT_LIMIT 0x1000000
/* Initial installation is from independently RAM-booted recovery. */
#define P1_STOCK_BOOTSTRAP 0
#endif
