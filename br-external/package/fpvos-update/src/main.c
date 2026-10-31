/* SPDX-License-Identifier: GPL-2.0-or-later */
/* One static executable, with legacy entry names retained for recovery scripts. */
#include <stdio.h>
#include <string.h>
#include "bootstrap.h"

int fpvos_receiver_main(int, char **);
int fpvos_verify_main(int, char **);
int fpvos_nand_main(int, char **);

int main(int argc, char **argv)
{
    const char *name = strrchr(argv[0], '/');
    name = name ? name + 1 : argv[0];
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
