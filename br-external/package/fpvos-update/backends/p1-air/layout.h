/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_P1_LAYOUT_H
#define FPVOS_P1_LAYOUT_H
#include <stdio.h>
#include <string.h>
#include "config.h"
#include "ar9311-gpt.h"
/* P1 fixed layout: only kernel/DTB/userapp selection may switch together.
 * SPL, environment, U-Boot and the stock bank's contents are preserved. */
/* Why GPT record SLOT is not a valid AR9311 record, in a few words. */
static inline void p1_gpt_problem(const unsigned char *g, unsigned slot, char *why, size_t n)
{
    unsigned erased = 1;
    for (unsigned i = 512; i < 604; i++) erased &= g[i] == 0xff;
    if (erased) { snprintf(why, n, "erased"); return; }
    if (memcmp(g + 512, "EFI PART", 8)) { snprintf(why, n, "no GPT header"); return; }
    unsigned long long last = ar9311_gpt_last(g, slot);
    if (last != 0x3f7ffU && last != 0x3ffffU) { snprintf(why, n, "disk ends 0x%llx", last); return; }
    snprintf(why, n, "bad header/CRC, lba 0x%llx", (unsigned long long)fpvos_get_le64(g + 536));
}
#define P1_WHY(...) do { if (why) snprintf(why, n, __VA_ARGS__); } while (0)
/* The layout check; WHY (when given) says what failed, short enough for the
 * updater's 60-character reply. */
static inline int p1_layout_why(const unsigned char records[2][AR9311_GPT_BYTES], unsigned *record, unsigned *bank,
                                char *why, size_t n)
{
    int valid[2];
    for (unsigned i = 0; i < 2; i++) {
        valid[i] = ar9311_gpt_valid(records[i], i);

    }
    if (!valid[0] && !valid[1]) {
        char a[48], b[48];
        p1_gpt_problem(records[0], 0, a, sizeof(a));
        p1_gpt_problem(records[1], 1, b, sizeof(b));
        P1_WHY("GPT: 0 %s; 1 %s", a, b);
        return 0;
    }
    /* both records describe the same disk */
    if (valid[0] && valid[1] && ar9311_gpt_last(records[0], 0) != ar9311_gpt_last(records[1], 1)) {
        P1_WHY("GPT: records end 0x%llx and 0x%llx", ar9311_gpt_last(records[0], 0), ar9311_gpt_last(records[1], 1));
        return 0;
    }
    if (valid[0] && valid[1] && fpvos_get_le32(records[0]+532) == fpvos_get_le32(records[1]+532) &&
        memcmp(records[0]+1024, records[1]+1024, 16384)) {
        P1_WHY("GPT: records differ at generation %u", (unsigned)fpvos_get_le32(records[0]+532));
        return 0;
    }
    unsigned selected = valid[1] && (!valid[0] || fpvos_get_le32(records[1]+532) > fpvos_get_le32(records[0]+532));
    static const struct { const char *name; unsigned start, size, active; } expected[] = {
        {"vendor",0x180000,0x80000,1}, {"factory",0x200000,0x600000,1},
        {"env0",0x800000,0x60000,P1_BOOT_BANK == 0}, {"env1",0x860000,0x60000,P1_BOOT_BANK == 1},
        {"uboot0",0x8c0000,0xc0000,P1_BOOT_BANK == 0}, {"uboot1",0x980000,0xc0000,P1_BOOT_BANK == 1},
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
            if (e[57+2*j]) { P1_WHY("GPT %u: entry %u name not ASCII", selected, i); return 0; }
            name[j] = e[56+2*j];
        }
        unsigned j;
        for (j = 0; j < sizeof(expected)/sizeof(expected[0]); j++) {
            if (strcmp(name, expected[j].name)) continue;
            const int variable_boot = P1_BOOT_BANK < 0 && j >= 2 && j <= 5;
            if (found & (1U<<j)) { P1_WHY("GPT %u: %s twice", selected, name); return 0; }
            if (fpvos_get_le64(e+32) != expected[j].start/512 ||
                fpvos_get_le64(e+40) != (expected[j].start+expected[j].size)/512-1) {
                P1_WHY("GPT %u: %s 0x%llx-0x%llx, not 0x%x+0x%x", selected, name,
                         (unsigned long long)fpvos_get_le64(e+32)*512, (unsigned long long)(fpvos_get_le64(e+40)+1)*512,
                         expected[j].start, expected[j].size);
                return 0;
            }
            if (!variable_boot && (j < 6 || j > 11) ? fpvos_get_le64(e+48) != (expected[j].active ? 1ULL<<47 : 0) : (fpvos_get_le64(e+48) & ~(1ULL<<47)) != 0) {
                P1_WHY("GPT %u: %s flags 0x%llx", selected, name, (unsigned long long)fpvos_get_le64(e+48));
                return 0;
            }
            if (variable_boot && fpvos_get_le64(e+48)) boot_group[(j-2)/2] |= 1U << ((j-2)%2);
            if (j >= 6 && j <= 11 && fpvos_get_le64(e+48)) active_group[(j-6)/2] |= 1U << ((j-6)%2);
            found |= 1U<<j;
            break;
        }
        if (j == sizeof(expected)/sizeof(expected[0])) { P1_WHY("GPT %u: unexpected partition %s", selected, name); return 0; }
    }
    for (unsigned j = 0; j < sizeof(expected)/sizeof(expected[0]); j++)
        if (!(found & (1U<<j))) { P1_WHY("GPT %u: no %s partition", selected, expected[j].name); return 0; }
    if ((active_group[0] != 1 && active_group[0] != 2) ||
        active_group[0] != active_group[1] || active_group[0] != active_group[2]) {
        P1_WHY("GPT %u: kernel/dtb/userapp banks %u/%u/%u", selected, active_group[0], active_group[1], active_group[2]);
        return 0;
    }
    if (P1_BOOT_BANK < 0 && ((boot_group[0] != 1 && boot_group[0] != 2) ||
        boot_group[0] != boot_group[1])) {
        P1_WHY("GPT %u: env/uboot banks %u/%u", selected, boot_group[0], boot_group[1]);
        return 0;
    }
    if (record) *record = selected;
    if (bank) *bank = active_group[0] == 2;
    return 1;
}
static inline int p1_layout(const unsigned char records[2][AR9311_GPT_BYTES], unsigned *record, unsigned *bank)
{ return p1_layout_why(records, record, bank, NULL, 0); }
static inline int p1_layout_valid(const unsigned char records[2][AR9311_GPT_BYTES])
{ return p1_layout(records, NULL, NULL); }
#endif
