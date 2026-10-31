/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_BOOTSTRAP_H
#define FPVOS_BOOTSTRAP_H
#include <stddef.h>
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
int fpvos_bootstrap_main(int, char **);
#endif
