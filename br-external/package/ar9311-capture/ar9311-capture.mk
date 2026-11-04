################################################################################
#
# ar9311-capture
#
################################################################################

AR9311_CAPTURE_VERSION = e3885c6394a7025eacd3a23f473276d9823beb25
AR9311_CAPTURE_SITE = $(call github,Missing-Lynk,ml-kernel,$(AR9311_CAPTURE_VERSION))
AR9311_CAPTURE_LICENSE = GPL-2.0
AR9311_CAPTURE_LICENSE_FILES = COPYING
AR9311_CAPTURE_MODULE_SUBDIRS = fpvos-capture

define AR9311_CAPTURE_PREPARE_MODULE
	mkdir -p $(@D)/fpvos-capture
	cp -a $(@D)/overlay/drivers/media/artosyn/*.h \
		$(@D)/overlay/drivers/media/artosyn/ar-*.c \
		$(@D)/overlay/drivers/media/artosyn/vendor-tables $(@D)/fpvos-capture/
	cp $(@D)/overlay/drivers/clk/clk-ar9311-cgu.c $(@D)/fpvos-capture/
	printf '%s\n' \
		'obj-m += ar-csi2.o ar-vif.o ar-isp.o ar-cvisp.o clk-ar9311-cgu.o' \
		'ar-isp-y := ar-isp-main.o ar-isp-tables.o' > $(@D)/fpvos-capture/Kbuild
endef
AR9311_CAPTURE_POST_PATCH_HOOKS += AR9311_CAPTURE_PREPARE_MODULE

$(eval $(kernel-module))
$(eval $(generic-package))
