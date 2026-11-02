/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_BOOTSTRAP_H
#define FPVOS_BOOTSTRAP_H
#include <stddef.h>
#include <limits.h>
struct fpvos_bootstrap_file {
    const char *path;
    const unsigned char *data;
    size_t length;
    unsigned mode;
};
struct fpvos_bootstrap_link { const char *path, *target; };
extern const struct fpvos_bootstrap_file fpvos_bootstrap_files[];
extern const size_t fpvos_bootstrap_file_count;
extern const struct fpvos_bootstrap_link fpvos_bootstrap_links[];
extern const size_t fpvos_bootstrap_link_count;
int fpvos_bootstrap_path(char out[PATH_MAX], const char *work, const char *relative);
int fpvos_bootstrap_copy(const char *source, const char *destination, unsigned mode);
int fpvos_bootstrap_extract(const char *work);
int fpvos_bootstrap_ram_directory(const char *work);
int fpvos_bootstrap_main(int, char **);
#endif
