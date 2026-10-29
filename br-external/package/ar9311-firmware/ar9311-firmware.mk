################################################################################
#
# ar9311-firmware
#
################################################################################

AR9311_FIRMWARE_VERSION = 17.5.8
AR9311_FIRMWARE_SOURCE_DIR ?= $(BR2_EXTERNAL_FPVOS_PATH)/../vendor/ar9311-firmware
AR9311_FIRMWARE_SITE = $(AR9311_FIRMWARE_SOURCE_DIR)
AR9311_FIRMWARE_SITE_METHOD = local
AR9311_FIRMWARE_LICENSE = PROPRIETARY
AR9311_FIRMWARE_REDISTRIBUTE = NO

# Local sources bypass download hash verification. Check explicitly before
# installing, including on a target reinstall from an existing build directory.
define AR9311_FIRMWARE_INSTALL_TARGET_CMDS
	test -f $(AR9311_FIRMWARE_PKGDIR)/ar9311-firmware.hash
	$(TOPDIR)/support/download/check-hash $(@D)/chagall.bin chagall.bin \
		$(AR9311_FIRMWARE_PKGDIR)/ar9311-firmware.hash
	# Do not follow a stale link to firmware on an SD filesystem.
	rm -f $(TARGET_DIR)/lib/firmware/artosyn/chagall.bin
	$(INSTALL) -D -m 0644 $(@D)/chagall.bin \
		$(TARGET_DIR)/lib/firmware/artosyn/chagall.bin
endef

$(eval $(generic-package))
