/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Boards updated another way (an SD card, the vendor's PC tool): the serial
 * port and the USB modes, no NAND and no stock-runtime bootstrap. */
#include <stdio.h>
#include "board.h"
#include "bootstrap.h"

int fpvos_board_image_valid(unsigned index, const unsigned char *data, size_t size, unsigned kind)
{
    (void)index; (void)data; (void)size; (void)kind;
    return 0;
}

int fpvos_nand_main(int argc, char **argv)
{
    (void)argc; (void)argv;
    fprintf(stderr, "no NAND on this board\n");
    return 2;
}

int fpvos_bootstrap_main(int argc, char **argv)
{
    (void)argc; (void)argv;
    fprintf(stderr, "no bootstrap on this board\n");
    return 2;
}
