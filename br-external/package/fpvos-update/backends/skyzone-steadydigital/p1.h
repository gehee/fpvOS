/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_P1_H
#define FPVOS_P1_H
#include <stddef.h>
#include "layout.h"
#include <sys/types.h>
#ifndef P1_WORK
#define P1_WORK "/run/fpvos-update"
#endif
#define P1_STATE P1_WORK "/state"
#define P1_FLAG P1_STATE "/sirius-clean-system-flag"
int p1_stock(void);
int p1_preflight(void);
int p1_state_mount(void);
int p1_state_unmount(void);
int p1_bundle_read(const char *destination);
int p1_bundle_write(const char *source);
int p1_bundle_present(void);
int p1_active_bank(unsigned *bank);
int p1_hash(const char *path, char hash[65]);
int p1_read(const char *path, char *text, size_t size);
int p1_copy_n(int in, int out, size_t size);
int p1_exact(int fd, void *buffer, size_t size, off_t offset);
int p1_read_checked(int fd, void *buffer, size_t size, off_t offset);
int p1_atomic(const char *path, const void *data, size_t size, unsigned mode);
int p1_mtd(const char *name, unsigned offset, unsigned size, unsigned *number);
int p1_gpt_read(unsigned char gpt[SD_GPT_BYTES]);
int p1_select_bank(unsigned bank);
int p1_flash_image(unsigned index, const char *path, int writing);
#endif
