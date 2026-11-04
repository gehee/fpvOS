################################################################################
#
# p1-air-camera-firmware
#
################################################################################

P1_AIR_CAMERA_FIRMWARE_VERSION = 1
P1_AIR_CAMERA_FIRMWARE_SOURCE =
P1_AIR_CAMERA_FIRMWARE_LICENSE = PROPRIETARY
P1_AIR_CAMERA_FIRMWARE_REDISTRIBUTE = NO
P1_AIR_CAMERA_FIRMWARE_DEPENDENCIES = p1-air-vendor host-squashfs

# Check extracted contents as well as the enclosing vendor release hash.
define P1_AIR_CAMERA_FIRMWARE_BUILD_CMDS
	$(HOST_DIR)/bin/unsquashfs -cat \
		$(P1_AIR_VENDOR_DIR)/stock/root.squashfs \
		usr/usrdata/tunning/sc231_tuning_preview_fpv.bin > $(@D)/sc231-tuning-preview-fpv.bin
	$(HOST_DIR)/bin/unsquashfs -cat \
		$(P1_AIR_VENDOR_DIR)/stock/root.squashfs \
		usr/bin/chagall_lowmem.bin.gz > $(@D)/chagall-lowmem.bin.gz
	$(ZCAT) $(@D)/chagall-lowmem.bin.gz > $(@D)/chagall-lowmem.bin
	cd $(@D) && sha256sum -c $(P1_AIR_CAMERA_FIRMWARE_PKGDIR)/files.sha256
endef

define P1_AIR_CAMERA_FIRMWARE_INSTALL_TARGET_CMDS
	cd $(@D) && sha256sum -c $(P1_AIR_CAMERA_FIRMWARE_PKGDIR)/files.sha256
	$(INSTALL) -D -m 0644 $(@D)/sc231-tuning-preview-fpv.bin \
		$(TARGET_DIR)/lib/firmware/artosyn/sc231-tuning-preview-fpv.bin
	$(INSTALL) -D -m 0644 $(@D)/chagall-lowmem.bin \
		$(TARGET_DIR)/lib/firmware/artosyn/p1-chagall-lowmem.bin
endef

$(eval $(generic-package))
