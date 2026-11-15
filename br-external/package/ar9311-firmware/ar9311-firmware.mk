################################################################################
#
# ar9311-firmware
#
################################################################################

# Source profile selected by board defconfig; reusable by compatible boards.
AR9311_FIRMWARE_PARTITION = userapp0
AR9311_FIRMWARE_PEB_SIZE = 131072
AR9311_FIRMWARE_VOLUME_ID = 0
AR9311_FIRMWARE_BLOB = chagall.bin
ifeq ($(BR2_PACKAGE_AR9311_FIRMWARE_ASCENT_17_5_15),y)
AR9311_FIRMWARE_VERSION = ascent-17.5.15
AR9311_FIRMWARE_SITE = https://github.com/CaddxFPV-Tech/Caddx-Ascent-Firmware-Release/releases/download/V17.5.15
AR9311_FIRMWARE_SOURCE = Ascent_G_Gnd_17_5_15.img
AR9311_FIRMWARE_MEMBER = usr/bin/chagall.bin
endif

ifeq ($(BR2_PACKAGE_AR9311_FIRMWARE_P1_GOGGLE_1_0_36),y)
AR9311_FIRMWARE_VERSION = p1-goggle-1.0.36
AR9311_FIRMWARE_SITE = https://drive.usercontent.google.com
AR9311_FIRMWARE_SOURCE = P1_GND_v1.0.36_20251110_49e4cf0.img
AR9311_FIRMWARE_MEMBER = usr/bin/chagall.bin.gz
AR9311_FIRMWARE_MEMBER_OPTIONS = --gzip-member
AR9311_FIRMWARE_BLOB = p1-goggle-chagall.bin
AR9311_FIRMWARE_DOWNLOAD_DEPENDENCIES = host-python3

# Drive's query cannot be expressed as SITE/SOURCE. Cache atomically, then
# retain Buildroot's normal hash check (also applied to local cache overrides).
define AR9311_FIRMWARE_FETCH
	mkdir -p $(AR9311_FIRMWARE_DL_DIR)
	flock $(AR9311_FIRMWARE_DL_DIR)/.p1-goggle-fetch.lock \
		$(HOST_DIR)/bin/python3 $(AR9311_FIRMWARE_PKGDIR)/fetch.py \
		$(AR9311_FIRMWARE_DL_DIR)/$(AR9311_FIRMWARE_SOURCE) \
		--url 'https://drive.usercontent.google.com/download?id=1w46-qQfq1BOkvLBl-uB4YNlsFR_0u6eA&export=download&confirm=t' \
		--sha256 4fd67842b03ef56602478b2420b8f68eb039eb03dc40198195cd1ba2acab1ecf \
		--max-bytes 67108864 --wget '$(call qstrip,$(BR2_WGET))'
endef
AR9311_FIRMWARE_PRE_DOWNLOAD_HOOKS += AR9311_FIRMWARE_FETCH
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
		--member $(AR9311_FIRMWARE_MEMBER) $(AR9311_FIRMWARE_MEMBER_OPTIONS) \
		--liblzo $(HOST_DIR)/lib/liblzo2.so \
		--unsquashfs $(HOST_DIR)/bin/unsquashfs \
		--output $(@D)/$(AR9311_FIRMWARE_BLOB)
endef

# Check the extracted blob even on a target reinstall from an existing build.
define AR9311_FIRMWARE_INSTALL_TARGET_CMDS
	test -f $(AR9311_FIRMWARE_PKGDIR)/ar9311-firmware.hash
	$(TOPDIR)/support/download/check-hash $(@D)/$(AR9311_FIRMWARE_BLOB) $(AR9311_FIRMWARE_BLOB) \
		$(AR9311_FIRMWARE_PKGDIR)/ar9311-firmware.hash
	# Do not follow a stale link to firmware on an SD filesystem.
	rm -f $(TARGET_DIR)/lib/firmware/artosyn/$(AR9311_FIRMWARE_BLOB)
	$(INSTALL) -D -m 0644 $(@D)/$(AR9311_FIRMWARE_BLOB) \
		$(TARGET_DIR)/lib/firmware/artosyn/$(AR9311_FIRMWARE_BLOB)
endef

$(eval $(generic-package))
