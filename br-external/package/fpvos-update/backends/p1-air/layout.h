/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_P1_LAYOUT_H
#define FPVOS_P1_LAYOUT_H
#include <string.h>
#include "ar9311-gpt.h"
/* P1 fixed layout: only kernel/DTB/userapp selection may switch together.
 * SPL, environment, U-Boot and the stock bank 1 contents are preserved. */
static inline int p1_layout(const unsigned char records[2][AR9311_GPT_BYTES], unsigned *record, unsigned *bank)
{
    int valid[2];
    for (unsigned i = 0; i < 2; i++) {
        valid[i] = ar9311_gpt_valid(records[i], i);

    }
    if (!valid[0] && !valid[1]) return 0;
    if (valid[0] && valid[1] && fpvos_get_le32(records[0]+532) == fpvos_get_le32(records[1]+532) &&
        memcmp(records[0]+1024, records[1]+1024, 16384)) return 0;
    unsigned selected = valid[1] && (!valid[0] || fpvos_get_le32(records[1]+532) > fpvos_get_le32(records[0]+532));
    static const struct { const char *name; unsigned start, size, active; } expected[] = {
        {"vendor",0x180000,0x80000,1}, {"factory",0x200000,0x600000,1},
        {"env0",0x800000,0x60000,0}, {"env1",0x860000,0x60000,1},
        {"uboot0",0x8c0000,0xc0000,0}, {"uboot1",0x980000,0xc0000,1},
        {"kernel0",0xa40000,0x600000,0}, {"kernel1",0x1040000,0x600000,1},
        {"dtb0",0x1640000,0x60000,0}, {"dtb1",0x16a0000,0x60000,1},
        {"userapp0",0x1700000,0x2d00000,0}, {"userapp1",0x4400000,0x2d00000,1},
        {"usr_data",0x7100000,0x600000,1}, {"usr_log",0x7700000,0x600000,1}
    };
    unsigned found = 0, active_group[3] = {0}, boot_group[2] = {0};
    for (unsigned i = 0; i < 128; i++) {
        const unsigned char *e = records[selected] + 1024 + 128*i;
        unsigned nonzero = 0;
        for (unsigned j = 0; j < 128; j++) nonzero |= e[j];
        if (!nonzero) continue;
        char name[37] = {0};
        for (unsigned j = 0; j < 36; j++) {
            if (e[57+2*j]) return 0;
            name[j] = e[56+2*j];
        }
        unsigned j;
        for (j = 0; j < sizeof(expected)/sizeof(expected[0]); j++) {
            if (strcmp(name, expected[j].name)) continue;
            if ((found & (1U<<j)) || fpvos_get_le64(e+32) != expected[j].start/512 ||
                fpvos_get_le64(e+40) != (expected[j].start+expected[j].size)/512-1 ||
                (j < 2 || j > 11 ? fpvos_get_le64(e+48) != (expected[j].active ? 1ULL<<47 : 0) : (fpvos_get_le64(e+48) & ~(1ULL<<47)) != 0)) return 0;
            /* Stock updates can select either environment/U-Boot copy. Require
             * exactly one of each, but preserve those selections unchanged. */
            if (j >= 2 && j <= 5 && fpvos_get_le64(e+48)) boot_group[(j-2)/2] |= 1U << ((j-2)%2);
            if (j >= 6 && j <= 11 && fpvos_get_le64(e+48)) active_group[(j-6)/2] |= 1U << ((j-6)%2);
            found |= 1U<<j;
            break;
        }
        if (j == sizeof(expected)/sizeof(expected[0])) return 0;
    }
    if (found != (1U<<14)-1 || (boot_group[0] != 1 && boot_group[0] != 2) ||
        (boot_group[1] != 1 && boot_group[1] != 2) || (active_group[0] != 1 && active_group[0] != 2) ||
        active_group[0] != active_group[1] || active_group[0] != active_group[2]) return 0;
    if (record) *record = selected;
    if (bank) *bank = active_group[0] == 2;
    return 1;
}
static inline int p1_layout_valid(const unsigned char records[2][AR9311_GPT_BYTES])
{ return p1_layout(records, NULL, NULL); }
#endif
