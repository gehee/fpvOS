/* SPDX-License-Identifier: GPL-3.0-only */
#include "awb.h"
#include <math.h>
#include <stdlib.h>

static uint32_t le32(const uint8_t *p)
{
	return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
	       (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static int compare(const void *a, const void *b)
{
	double x = *(const double *)a, y = *(const double *)b;
	return (x > y) - (x < y);
}

static unsigned int approach(unsigned int current, double target)
{
	int delta;
	if (target < 128) target = 128;
	if (target > 1024) target = 1024;
	if (fabs(target - current) <= 2) return current;
	delta = (int)lround((target - current) / 8);
	if (!delta) delta = target > current ? 1 : -1;
	if (delta > 8) delta = 8;
	if (delta < -8) delta = -8;
	return current + delta;
}

unsigned int awb_update(struct awb_state *s, const uint8_t *rro)
{
	double reds[AWB_BLOCKS * AWB_CELLS], blues[AWB_BLOCKS * AWB_CELLS];
	unsigned int n = 0, blocks = 0;
	for (unsigned int block = 0; block < AWB_BLOCKS; block++) {
		unsigned int before = n;
		for (unsigned int cell = 0; cell < AWB_CELLS; cell++) {
			const uint8_t *p = rro + block * 512 + cell * 16;
			double v[4], g, r, b;
			unsigned int c;
			for (c = 0; c < 4; c++) {
				uint32_t count = le32(p + c * 4);
				if (!count) break;
				v[c] = (double)le32(p + 256 + c * 4) / count;
				/* Reject dark/noisy, clipped and malformed statistics. */
				if (v[c] < 5 || v[c] > 235) break;
			}
			if (c != 4) continue;
			g = (v[s->g1] + v[s->g2]) / 2;
			if (g < 8 || fabs(v[s->g1] - v[s->g2]) > g * .25) continue;
			r = v[s->r] * s->anchor_red / (256 * g);
			b = v[s->b] * s->anchor_blue / (256 * g);
			/* Fixed anchor prevents feedback from progressively accepting
			 * saturated objects as neutrals. This is a conservative grey
			 * selection, not a general illuminant classifier. */
			if (r < .65 || r > 1.45 || b < .65 || b > 1.45) continue;
			reds[n] = 256 * g / v[s->r];
			blues[n++] = 256 * g / v[s->b];
		}
		if (n != before) blocks++;
	}
	if (n < 32 || blocks < 8) return 0;
	qsort(reds, n, sizeof(*reds), compare);
	qsort(blues, n, sizeof(*blues), compare);
	s->red = approach(s->red, (reds[(n - 1) / 2] + reds[n / 2]) / 2);
	s->blue = approach(s->blue, (blues[(n - 1) / 2] + blues[n / 2]) / 2);
	return n;
}
