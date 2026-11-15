// SPDX-License-Identifier: GPL-2.0-or-later
// The AR9311's SoC temperature sensor (the vendor DT's "artosyn,protemp",
// temperature@a108000) as hwmon temp1_input, for kernels without IIO. The
// block free-runs a 9-bit code at 0xcc (bits 7:0) and 0xd0 (bit 0, bit 8);
// probe enables it as the vendor driver does (CTRL bit 0, CFG bits 6:4).
// Conversion is the vendor's, kept linear here to the millidegree:
// T = (code * 5320 - 1373400) / 10000 degrees C (300 -> 22, 355 -> 51).
// Register map and conversion: Missing-Lynk ml-kernel
// docs/artosyn-protemp.md and modules/artosyn_protemp.c, which is the IIO
// version of the same driver.
//
// With "artosyn,vin-channel" and "artosyn,vin-ratio-permille" in its node,
// and a window covering the SAR ADC (0x21c, the vendor's adc@a108000), it is
// the board's supply as in0_input too, in millivolts: the SAR ADC (10-bit)
// sampled as the vendor driver does (Missing-Lynk docs/artosyn-adc.md) and
// scaled by the board's divider. The pin's millivolts follow stock P1's own
// two points (its adc.sh: code 425 = 887 mV, 573 = 1180 mV), offset by the
// channel's own reading of the on-chip reference (code 425 there), taken at
// probe, as the vendor does.
#include <linux/hwmon.h>
#include <linux/io.h>
#include <linux/module.h>
#include <linux/mod_devicetable.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/sort.h>

#define CTRL		0x00
#define CTRL_EN		BIT(0)
#define CFG		0x38
#define CFG_BITS	0x70
#define DATA_LO		0xcc
#define DATA_HI		0xd0
#define SAMPLES		8

#define ADC_EN		BIT(7)		/* in CTRL */
#define ADC_SAMPLE	0x18		/* 0: a burst, 1: done */
#define ADC_CHAN	0x24
#define ADC_CALIB	0x2c
#define ADC_CALIB_REF	BIT(3)		/* the channel reads the on-chip reference */
#define ADC_RESET	0x200
#define ADC_DATA	0x210
#define ADC_WINDOW	0x214
#define ADC_SAMPLES	64		/* the vendor DT's samp-count */
#define ADC_REF_MV	887		/* stock P1 adc.sh: code 425 */
#define ADC_SLOPE_UV	1980		/* (1180 - 887) mV over (573 - 425) codes */

struct ar9311_temp {
	void __iomem *regs;
	struct mutex adc_lock;
	u32 vin_channel;
	u32 vin_ratio;			/* per mille, 0: no in0 */
	int vin_ref;			/* the channel's reference code */
};

static int cmp_u16(const void *a, const void *b)
{
	return *(const u16 *)a - *(const u16 *)b;
}

/* Eight back-to-back codes, the outer quarter dropped, the rest averaged. */
static unsigned int ar9311_temp_code(struct ar9311_temp *t)
{
	u16 s[SAMPLES];
	unsigned int sum = 0;

	for (int i = 0; i < SAMPLES; i++)
		s[i] = (readl(t->regs + DATA_LO) & 0xff) | (readl(t->regs + DATA_HI) & 1) << 8;
	sort(s, SAMPLES, sizeof(s[0]), cmp_u16, NULL);
	for (int i = 1; i < SAMPLES - 1; i++)
		sum += s[i];
	return DIV_ROUND_CLOSEST(sum, SAMPLES - 2);
}

/* One reading of a channel as the vendor takes it: select, open a burst, 16
 * reads to settle, ADC_SAMPLES kept, close; the outer eighths dropped. */
static int ar9311_adc_code(struct ar9311_temp *t, u32 channel, bool ref)
{
	u16 s[ADC_SAMPLES];
	unsigned int sum = 0;
	int i;

	mutex_lock(&t->adc_lock);
	if (ref)
		writel(readl(t->regs + ADC_CALIB) | ADC_CALIB_REF, t->regs + ADC_CALIB);
	writel(channel & 0xff, t->regs + ADC_CHAN);
	writel(0, t->regs + ADC_SAMPLE);
	for (i = 0; i < 16; i++)
		readl(t->regs + ADC_DATA);
	for (i = 0; i < ADC_SAMPLES; i++)
		s[i] = readl(t->regs + ADC_DATA) & 0x3ff;
	writel(1, t->regs + ADC_SAMPLE);
	if (ref)
		writel(readl(t->regs + ADC_CALIB) & ~ADC_CALIB_REF, t->regs + ADC_CALIB);
	mutex_unlock(&t->adc_lock);

	sort(s, ADC_SAMPLES, sizeof(s[0]), cmp_u16, NULL);
	for (i = ADC_SAMPLES / 8; i < ADC_SAMPLES - ADC_SAMPLES / 8; i++)
		sum += s[i];
	return DIV_ROUND_CLOSEST(sum, ADC_SAMPLES - ADC_SAMPLES / 4);
}

static long ar9311_vin_mv(struct ar9311_temp *t)
{
	long pin_uv = ADC_REF_MV * 1000L +
		      (long)(ar9311_adc_code(t, t->vin_channel, false) - t->vin_ref) * ADC_SLOPE_UV;

	return pin_uv <= 0 ? 0 : pin_uv * t->vin_ratio / 1000000;
}

/* The vendor probe's order: data path reset, reference off, burst closed,
 * then the enable (CTRL is shared with the temperature engine: one bit). */
static void ar9311_adc_init(struct ar9311_temp *t)
{
	writel(0, t->regs + ADC_RESET);
	writel(readl(t->regs + ADC_CALIB) & ~ADC_CALIB_REF, t->regs + ADC_CALIB);
	writel(1, t->regs + ADC_SAMPLE);
	writel(readl(t->regs + CTRL) | ADC_EN, t->regs + CTRL);
	t->vin_ref = ar9311_adc_code(t, t->vin_channel, true);
}

static umode_t ar9311_temp_visible(const void *data, enum hwmon_sensor_types type,
				   u32 attr, int channel)
{
	const struct ar9311_temp *t = data;

	if (type == hwmon_temp)
		return attr == hwmon_temp_input ? 0444 : 0;
	if (type == hwmon_in && t->vin_ratio)
		return attr == hwmon_in_input || attr == hwmon_in_label ? 0444 : 0;
	return 0;
}

static int ar9311_temp_read(struct device *dev, enum hwmon_sensor_types type,
			    u32 attr, int channel, long *val)
{
	struct ar9311_temp *t = dev_get_drvdata(dev);

	if (type == hwmon_in && attr == hwmon_in_input) {
		*val = ar9311_vin_mv(t);
		return 0;
	}
	if (type != hwmon_temp || attr != hwmon_temp_input)
		return -EOPNOTSUPP;
	/* millidegrees: (code * 5320 - 1373400) / 10 */
	*val = ((long)ar9311_temp_code(t) * 5320 - 1373400) / 10;
	return 0;
}

static int ar9311_temp_read_string(struct device *dev, enum hwmon_sensor_types type,
				   u32 attr, int channel, const char **str)
{
	if (type != hwmon_in || attr != hwmon_in_label)
		return -EOPNOTSUPP;
	*str = "vin";
	return 0;
}

static const struct hwmon_ops ar9311_temp_ops = {
	.is_visible = ar9311_temp_visible,
	.read = ar9311_temp_read,
	.read_string = ar9311_temp_read_string,
};

static const struct hwmon_channel_info *const ar9311_temp_info[] = {
	HWMON_CHANNEL_INFO(temp, HWMON_T_INPUT),
	HWMON_CHANNEL_INFO(in, HWMON_I_INPUT | HWMON_I_LABEL),
	NULL
};

static const struct hwmon_chip_info ar9311_temp_chip = {
	.ops = &ar9311_temp_ops,
	.info = ar9311_temp_info,
};

static int ar9311_temp_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct ar9311_temp *t;
	struct resource *r;
	struct device *hw;

	t = devm_kzalloc(dev, sizeof(*t), GFP_KERNEL);
	if (!t)
		return -ENOMEM;
	r = platform_get_resource(pdev, IORESOURCE_MEM, 0);
	if (!r)
		return -EINVAL;
	/* Not exclusive: the SAR ADC's window covers this one (vendor DT). */
	t->regs = devm_ioremap(dev, r->start, resource_size(r));
	if (!t->regs)
		return -ENOMEM;
	writel(readl(t->regs + CTRL) | CTRL_EN, t->regs + CTRL);
	writel(readl(t->regs + CFG) | CFG_BITS, t->regs + CFG);

	mutex_init(&t->adc_lock);
	if (!of_property_read_u32(dev->of_node, "artosyn,vin-channel", &t->vin_channel) &&
	    !of_property_read_u32(dev->of_node, "artosyn,vin-ratio-permille", &t->vin_ratio) &&
	    t->vin_ratio) {
		if (t->vin_channel > 7 || resource_size(r) < ADC_WINDOW) {
			dev_warn(dev, "vin: channel %u or a window of %#llx unusable, no in0\n",
				 t->vin_channel, (unsigned long long)resource_size(r));
			t->vin_ratio = 0;
		} else {
			ar9311_adc_init(t);
			dev_info(dev, "vin: channel %u, reference code %d, x%u.%03u\n",
				 t->vin_channel, t->vin_ref, t->vin_ratio / 1000, t->vin_ratio % 1000);
		}
	}

	hw = devm_hwmon_device_register_with_info(dev, "ar9311_temp", t, &ar9311_temp_chip, NULL);
	return PTR_ERR_OR_ZERO(hw);
}

static const struct of_device_id ar9311_temp_of[] = {
	{ .compatible = "artosyn,protemp" },
	{ }
};
MODULE_DEVICE_TABLE(of, ar9311_temp_of);

static struct platform_driver ar9311_temp_driver = {
	.probe = ar9311_temp_probe,
	.driver = {
		.name = "ar9311-temp",
		.of_match_table = ar9311_temp_of,
	},
};
module_platform_driver(ar9311_temp_driver);

MODULE_DESCRIPTION("AR9311 SoC temperature sensor and board supply (hwmon)");
MODULE_LICENSE("GPL");
