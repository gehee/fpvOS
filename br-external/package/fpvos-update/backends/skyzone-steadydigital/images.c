/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "board.h"
#include "fpvos-bytes.h"
#include "ar9311-image.h"
#include "root.h"
#include <libfdt.h>
#include <string.h>
int fpvos_board_image_valid(unsigned index, const unsigned char *data, size_t size, unsigned kind)
{
    if (kind || index > 2) return 0;
    if (index == 0) {
        return size >= 135 && size <= 0x600000 && ar9311_kernel_valid(data,size,0x20200000) &&
               !memcmp(data+128,"\x04\x22\x4d\x18",4) && (data[132]&0xe0) == 0x60 &&
               !memcmp(data+96,"fpvOS SteadyDigital recovery",28);
    }
    if (index == 1) {
        return size >= 40 && size <= 0xf000 && !fdt_check_full(data, size) &&
               (size_t)fdt_totalsize(data) == size &&
               !fdt_node_check_compatible(data, 0, "skyzone,steadydigital");
    }
    return size <= fpvos_board.limits[2] && sd_root_valid(data,size,size);
}
