/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef FPVOS_AR9311_BANKS_H
#define FPVOS_AR9311_BANKS_H
/* Which bank an install writes and which one "stock" selects, on the A/B
 * AR9311 boards (P1 Air, P1 goggles, SteadyDigital). Neither bank is fpvOS's
 * or stock's for good, so each is judged by what it holds:
 *
 *   bundle  its bundle volume: 1 an fpvOS bundle, 0 readable and something
 *           else (stock's root), -1 unusable (in use, not attachable, wrong)
 *   kernel  its kernel partition: 1 fpvOS's kernel, 0 another OTRA/uImage
 *           kernel (stock's: SPL boots nothing else), -1 none or unreadable
 *
 * A bank is fpvOS's when either says so: a booted fpvOS whose bundle cannot be
 * read (damaged, or held as the running root) still has its kernel. It is
 * stock's only when both say stock. A bank that is neither is never taken for
 * stock: an install refuses rather than guess which bank stock is on. */
struct ar9311_bank { int bundle, kernel; };

static inline int ar9311_bank_fpvos(const struct ar9311_bank *b) { return b->bundle == 1 || b->kernel == 1; }
static inline int ar9311_bank_stock(const struct ar9311_bank *b) { return b->bundle == 0 && b->kernel == 0; }

enum ar9311_choice {
    AR9311_CHOSEN,
    AR9311_UNUSABLE,   /* the bank to write has an unusable bundle volume */
    AR9311_UNKNOWN,    /* fpvOS runs, the booted bank is neither fpvOS nor stock */
    AR9311_NO_STOCK,   /* no bank holds an intact stock system */
};

/* stock_runtime: the running system is stock, from the booted bank. Otherwise
 * fpvOS runs: booted from the bank (normal or clean recovery), or uploaded to
 * RAM over whatever the booted bank holds (the HID loader). */
static inline int ar9311_booted_is_stock(int stock_runtime, unsigned active, const struct ar9311_bank b[2])
{
    return stock_runtime || (!ar9311_bank_fpvos(&b[active]) && ar9311_bank_stock(&b[active]));
}

/* An update rewrites the booted fpvOS bank in place (or, with fpvOS on both,
 * the other one, so the booted one stays the fallback); a first install from
 * stock writes the bank stock does not boot from. The booted stock is never the
 * target, and neither is a bank this cannot tell is not stock. */
static inline enum ar9311_choice ar9311_install_bank(int stock_runtime, unsigned active,
                                                     const struct ar9311_bank b[2], unsigned *target)
{
    unsigned other = active ^ 1;
    if (!stock_runtime && ar9311_bank_fpvos(&b[active]))
        *target = ar9311_bank_fpvos(&b[other]) ? other : active;
    else if (ar9311_booted_is_stock(stock_runtime, active, b))
        *target = other;
    else
        return AR9311_UNKNOWN;
    return b[*target].bundle < 0 ? AR9311_UNUSABLE : AR9311_CHOSEN;
}

/* The bank that holds stock: the booted one when it is stock, else the other
 * when it is. Never a bank that may not boot (no stock kernel, or a bundle
 * volume that cannot be read). */
static inline enum ar9311_choice ar9311_stock_bank(int stock_runtime, unsigned active,
                                                   const struct ar9311_bank b[2], unsigned *bank)
{
    unsigned other = active ^ 1;
    if (ar9311_booted_is_stock(stock_runtime, active, b)) *bank = active;
    else if (!ar9311_bank_fpvos(&b[other]) && ar9311_bank_stock(&b[other])) *bank = other;
    else return AR9311_NO_STOCK;
    return AR9311_CHOSEN;
}
#endif
