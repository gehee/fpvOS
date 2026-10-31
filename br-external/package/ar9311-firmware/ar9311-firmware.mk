################################################################################
#
# ar9311-firmware
#
################################################################################

# Source profile selected by board defconfig; reusable by compatible boards.
ifeq ($(BR2_PACKAGE_AR9311_FIRMWARE_ASCENT_17_5_15),y)
AR9311_FIRMWARE_VERSION = ascent-17.5.15
AR9311_FIRMWARE_SITE = https://github.com/CaddxFPV-Tech/Caddx-Ascent-Firmware-Release/releases/download/V17.5.15
AR9311_FIRMWARE_SOURCE = Ascent_G_Gnd_17_5_15.img
AR9311_FIRMWARE_PARTITION = userapp0
AR9311_FIRMWARE_PEB_SIZE = 131072
AR9311_FIRMWARE_VOLUME_ID = 0
AR9311_FIRMWARE_MEMBER = usr/bin/chagall.bin
endif

AR9311_FIRMWARE_LICENSE = PROPRIETARY
AR9311_FIRMWARE_REDISTRIBUTE = NO
AR9311_FIRMWARE_DEPENDENCIES = host-python3 host-lzo host-squashfs

# The download is an OTRA image, not a tar archive. Host dependencies are
# available at build time; leave the normal download/cache/hash steps intact.
define AR9311_FIRMWARE_EXTRACT_CMDS
	cp $(AR9311_FIRMWARE_DL_DIR)/$(AR9311_FIRMWARE_SOURCE) $(@D)/$(AR9311_FIRMWARE_SOURCE)
endef

define AR9311_FIRMWARE_BUILD_CMDS
	$(TOPDIR)/support/download/check-hash $(@D)/$(AR9311_FIRMWARE_SOURCE) \
		$(AR9311_FIRMWARE_SOURCE) $(AR9311_FIRMWARE_PKGDIR)/ar9311-firmware.hash
	$(HOST_DIR)/bin/python3 $(AR9311_FIRMWARE_PKGDIR)/extract-ascent-vrx-firmware.py \
		--image $(@D)/$(AR9311_FIRMWARE_SOURCE) \
		--partition $(AR9311_FIRMWARE_PARTITION) \
		--peb-size $(AR9311_FIRMWARE_PEB_SIZE) \
		--volume-id $(AR9311_FIRMWARE_VOLUME_ID) \
		--member $(AR9311_FIRMWARE_MEMBER) \
		--liblzo $(HOST_DIR)/lib/liblzo2.so \
		--unsquashfs $(HOST_DIR)/bin/unsquashfs \
		--output $(@D)/chagall.bin
endef

# Check the extracted blob even on a target reinstall from an existing build.
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
