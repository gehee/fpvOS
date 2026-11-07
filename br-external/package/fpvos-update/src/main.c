/* SPDX-License-Identifier: GPL-2.0-or-later */
/* One static executable, with legacy entry names retained for recovery scripts. */
#include <stdio.h>
#include <string.h>
#include "bootstrap.h"

int fpvos_receiver_main(int, char **);
int fpvos_verify_main(int, char **);
int fpvos_nand_main(int, char **);
/* A board started under its vendor's updater name, or as its own helper:
 * -1 when it is neither. */
int fpvos_board_main(int, char **) __attribute__((weak));

int main(int argc, char **argv)
{
    const char *name = strrchr(argv[0], '/');
    name = name ? name + 1 : argv[0];
    if (fpvos_board_main) {
        int r = fpvos_board_main(argc, argv);
        if (r != -1) return r;
    }
    if (!strcmp(name, "fpvos-update-receiver")) return fpvos_receiver_main(argc, argv);
    if (!strcmp(name, "fpvos-update-verify")) return fpvos_verify_main(argc, argv);
    if (!strcmp(name, "ar9311-nandctl")) return fpvos_nand_main(argc, argv);
    if (argc > 1) {
        if (!strcmp(argv[1], "receive")) return fpvos_receiver_main(argc - 1, argv + 1);
        if (!strcmp(argv[1], "verify")) return fpvos_verify_main(argc - 1, argv + 1);
        if (!strcmp(argv[1], "nand")) return fpvos_nand_main(argc - 1, argv + 1);
        if (!strcmp(argv[1], "bootstrap")) return fpvos_bootstrap_main(argc - 1, argv + 1);
    }
    fprintf(stderr, "Usage: fpvos-update {receive TTY STAGING HELPER|verify PACKAGE OUTPUT|nand {preflight|install PACKAGE|boot|clean}|bootstrap}\n");
    return 2;
}
