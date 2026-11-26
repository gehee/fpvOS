/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "board.h"
#include "config.h"
#include "fpvos-bytes.h"
#include "ar9311-image.h"
#include <libfdt.h>
#include <stdio.h>
#include <string.h>
#ifndef P1_UNIT_TREE
#define P1_UNIT_TREE "/proc/device-tree/compatible"
#endif
/* The board's device tree: P1_COMPATIBLE. A backend covering several units
 * (the P1 ground units: P1_COMPATIBLE the goggles' tree, P1_COMPATIBLE_ALT the
 * Nano VRX's, P1_COMPATIBLE_ALT2 the goggles Pro's) takes only the tree of
 * the unit it runs on - another unit's bundle differs in nothing else, and
 * its tree would start this one with the wrong screen. A stock unit's RAM
 * recovery runs on none of theirs (P1_COMPATIBLE_ANY, any unit of the
 * backend) and takes any: the bundle chosen names the unit. */
#ifdef P1_COMPATIBLE_ALT
#ifndef P1_COMPATIBLE_ALT2
#define P1_COMPATIBLE_ALT2 P1_COMPATIBLE_ALT
#endif
static int unit_tree(const char *name)
{
    return !strcmp(name, P1_COMPATIBLE) || !strcmp(name, P1_COMPATIBLE_ALT) ||
           !strcmp(name, P1_COMPATIBLE_ALT2);
}
#endif
static int board_tree(const unsigned char *data)
{
#ifdef P1_COMPATIBLE_ALT
    char unit[64] = {0};
    FILE *f = fopen(P1_UNIT_TREE, "rb");
    size_t n = f ? fread(unit, 1, sizeof(unit)-1, f) : 0;
    if (f) fclose(f);
#ifdef P1_COMPATIBLE_ANY
    if (n && !strcmp(unit, P1_COMPATIBLE_ANY))
        return !fdt_node_check_compatible(data, 0, P1_COMPATIBLE) ||
               !fdt_node_check_compatible(data, 0, P1_COMPATIBLE_ALT) ||
               !fdt_node_check_compatible(data, 0, P1_COMPATIBLE_ALT2);
#endif
    if (!n || !unit_tree(unit)) return 0;
    return !fdt_node_check_compatible(data, 0, unit);
#else
    return !fdt_node_check_compatible(data, 0, P1_COMPATIBLE);
#endif
}

int fpvos_board_image_valid(unsigned index, const unsigned char *data, size_t size, unsigned kind)
{
    if (kind || index > 2) return 0;
    if (index == 0) {
        return size >= 135 && size <= 0x600000 && ar9311_kernel_valid(data,size,0x20200000) &&
               !memcmp(data+128,"\x04\x22\x4d\x18",4) && (data[132]&0xe0) == 0x60 &&
               !memcmp(data+96,P1_KERNEL_NAME,sizeof(P1_KERNEL_NAME));
    }
    if (index == 1) {
        return size >= 40 && size <= 0xf000 && !fdt_check_full(data, size) &&
               (size_t)fdt_totalsize(data) == size &&
               board_tree(data);
    }
    return size >= 18 && size <= P1_ROOT_LIMIT && data[0] == 0x1f && data[1] == 0x8b && data[2] == 8;
}
