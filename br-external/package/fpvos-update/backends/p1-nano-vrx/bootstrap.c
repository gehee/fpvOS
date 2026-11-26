/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <stdio.h>
int fpvos_bootstrap_main(int argc, char **argv)
{
    (void)argc; (void)argv;
    fputs("The P1 Nano VRX requires a RAM-booted fpvOS recovery installer\n", stderr);
    return 1;
}
