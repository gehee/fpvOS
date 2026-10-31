################################################################################
#
# ar9311-mmc
#
################################################################################

AR9311_MMC_VERSION = e3885c6394a7025eacd3a23f473276d9823beb25
AR9311_MMC_SITE = $(call github,Missing-Lynk,ml-kernel,$(AR9311_MMC_VERSION))
AR9311_MMC_LICENSE = GPL-2.0
AR9311_MMC_LICENSE_FILES = COPYING
AR9311_MMC_MODULE_SUBDIRS = fpvos-mmc

# Upstream's module directory contains unrelated bring-up experiments.
# Build the MMC wrapper and GPIO provider for the SD voltage regulator.
# Source clocks and gates are owned by the kernel's AR9311 CCF provider.
# The mainline dw_mmc core and regulator-gpio drivers remain unmodified.
define AR9311_MMC_PREPARE_MODULE
	mkdir -p $(@D)/fpvos-mmc
	cp $(@D)/modules/dw_mci-artosyn.c $(@D)/fpvos-mmc/
	cp $(@D)/modules/artosyn_gpio.c $(@D)/fpvos-mmc/
	printf '%s\n' 'obj-m += dw_mci-artosyn.o artosyn_gpio.o' \
		'CFLAGS_dw_mci-artosyn.o := -I$$(srctree)/drivers/mmc/host' \
		> $(@D)/fpvos-mmc/Kbuild
endef
AR9311_MMC_POST_PATCH_HOOKS += AR9311_MMC_PREPARE_MODULE

$(eval $(kernel-module))
$(eval $(generic-package))
