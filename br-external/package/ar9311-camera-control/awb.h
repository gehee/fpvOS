/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FPVOS_AWB_H
#define FPVOS_AWB_H

#include <stddef.h>
#include <stdint.h>

#define AWB_BLOCKS 36
#define AWB_CELLS 16
#define AWB_RRO_SIZE (AWB_BLOCKS * 512)
#define AWB_STATS_SIZE (4 + AWB_RRO_SIZE + 4096 + 4)

struct awb_state {
	unsigned int red, blue;
	unsigned int anchor_red, anchor_blue;
	/* Statistics order, which need not match the sensor bus Bayer order. */
	unsigned int r, g1, g2, b;
};

/* Returns the number of accepted zones, or zero when holding the gains. */
unsigned int awb_update(struct awb_state *state, const uint8_t *rro);

#endif
