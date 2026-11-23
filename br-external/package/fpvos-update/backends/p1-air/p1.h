/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_P1_H
#define FPVOS_P1_H
#include <stddef.h>
#include "config.h"
#include "ar9311-gpt.h"
#include <sys/types.h>
#ifndef P1_WORK
#define P1_WORK "/run/fpvos-update"
#endif
#define P1_STATE P1_WORK "/state"
#define P1_FLAG P1_STATE "/sirius-clean-system-flag"
/* No bank is fpvOS's or stock's for good: each install writes the bank the
 * choice in nand.c picks (the one already holding fpvOS, else the one not
 * booted), and the other keeps what it holds. Both banks sit at the standard
 * P1 NAND offsets (layout.h), so a bank number is all a write needs. */
static inline const char *p1_kernel_part(unsigned bank) { return bank ? "kernel1" : "kernel0"; }
static inline unsigned p1_kernel_offset(unsigned bank) { return bank ? 0x1040000 : 0xa40000; }
static inline const char *p1_dtb_part(unsigned bank) { return bank ? "dtb1" : "dtb0"; }
static inline unsigned p1_dtb_offset(unsigned bank) { return bank ? 0x16a0000 : 0x1640000; }
static inline const char *p1_root_part(unsigned bank) { return bank ? "userapp1" : "userapp0"; }
static inline unsigned p1_root_offset(unsigned bank) { return bank ? 0x4400000 : 0x1700000; }
int p1_stock(void);
int p1_preflight(void);
int p1_state_mount(void);
int p1_state_unmount(void);
int p1_bundle_read(unsigned bank, const char *destination);
int p1_bundle_write(unsigned bank, const char *source);
int p1_bundle_present(unsigned bank);
int p1_active_bank(unsigned *bank);
int p1_hash(const char *path, char hash[65]);
int p1_read(const char *path, char *text, size_t size);
int p1_copy_n(int in, int out, size_t size);
int p1_exact(int fd, void *buffer, size_t size, off_t offset);
int p1_read_checked(int fd, void *buffer, size_t size, off_t offset);
int p1_atomic(const char *path, const void *data, size_t size, unsigned mode);
int p1_mtd(const char *name, unsigned offset, unsigned size, unsigned *number);
int p1_gpt_read(unsigned char gpt[2][AR9311_GPT_BYTES]);
int p1_select_bank(unsigned bank);
int p1_flash_image(unsigned bank, unsigned index, const char *path, int writing);
#endif
