// SPDX-License-Identifier: GPL-2.0-or-later
// AR8030 changes SDIO identity after its RAM firmware is uploaded. A normal
// mmc-pwrseq-simple power-off reset erases that firmware during re-enumeration.
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/mmc/host.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include "pwrseq.h"

struct ar9311_radio_pwrseq {
	struct mmc_pwrseq pwrseq;
	struct gpio_desc *reset;
	bool started;
};

static void radio_post_power_on(struct mmc_host *host)
{
	struct ar9311_radio_pwrseq *radio =
		container_of(host->pwrseq, struct ar9311_radio_pwrseq, pwrseq);

	/* Serialized by the MMC host. The board keeps the supply rails on. */
	if (radio->started)
		return;
	/* Stock Gnd485 sequence: assert for 100 ms, release, wait 1 second. */
	msleep(100);
	gpiod_set_value_cansleep(radio->reset, 0);
	msleep(1000);
	radio->started = true;
}

static const struct mmc_pwrseq_ops radio_ops = {
	.post_power_on = radio_post_power_on,
	/* Deliberately no power_off callback: retain RAM across SDIO removal. */
};

static int radio_probe(struct platform_device *pdev)
{
	struct ar9311_radio_pwrseq *radio;

	radio = devm_kzalloc(&pdev->dev, sizeof(*radio), GFP_KERNEL);
	if (!radio)
		return -ENOMEM;
	radio->reset = devm_gpiod_get(&pdev->dev, "reset", GPIOD_OUT_HIGH);
	if (IS_ERR(radio->reset))
		return dev_err_probe(&pdev->dev, PTR_ERR(radio->reset), "reset GPIO unavailable\n");
	radio->pwrseq.ops = &radio_ops;
	radio->pwrseq.dev = &pdev->dev;
	radio->pwrseq.owner = THIS_MODULE;
	platform_set_drvdata(pdev, radio);
	return mmc_pwrseq_register(&radio->pwrseq);
}

static void radio_remove(struct platform_device *pdev)
{
	struct ar9311_radio_pwrseq *radio = platform_get_drvdata(pdev);

	mmc_pwrseq_unregister(&radio->pwrseq);
}

static const struct of_device_id radio_match[] = {
	{ .compatible = "artosyn,ar8030-pwrseq" },
	{ }
};
MODULE_DEVICE_TABLE(of, radio_match);

static struct platform_driver radio_driver = {
	.probe = radio_probe,
	.remove = radio_remove,
	.driver = {
		.name = "ar9311-radio-pwrseq",
		.of_match_table = radio_match,
	},
};
module_platform_driver(radio_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Gnd485 AR8030 reset with firmware retention during SDIO re-enumeration");
