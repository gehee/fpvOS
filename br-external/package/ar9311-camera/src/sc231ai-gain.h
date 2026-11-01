/* SPDX-License-Identifier: GPL-2.0-only */
/* SC231AI gain register encoding. Indices follow the P1 sensor's 220
 * analogue and 128 digital gain steps, recovered from libsns_sc231ai.so.
 * Analogue index 0 is 1x and 219 is approximately 116.55x. Digital index
 * 0 is 1x and 127 is 15.75x. These are sensor controls, not ISP gain.
 */
#ifndef SC231AI_GAIN_H
#define SC231AI_GAIN_H

static inline void sc231ai_analogue_gain(unsigned int index,
					unsigned char *coarse, unsigned char *fine)
{
	static const unsigned char starts[] = { 0, 32, 60, 92, 124, 156, 188 };
	static const unsigned char codes[] = { 0, 1, 0x80, 0x81, 0x83, 0x87, 0x8f };
	unsigned int band = 0;

	while (band < 6 && index >= starts[band + 1])
		band++;
	*coarse = codes[band];
	*fine = 0x20 + index - starts[band];
}

static inline void sc231ai_digital_gain(unsigned int index,
				       unsigned char *coarse, unsigned char *fine)
{
	*coarse = (1U << (index / 32)) - 1;
	*fine = 0x80 + (index % 32) * 4;
}

#endif
