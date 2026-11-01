################################################################################
#
# p1-air-vendor
#
################################################################################

P1_AIR_VENDOR_VERSION = 1.0.44
P1_AIR_VENDOR_SOURCE = P1_SKY_v1.0.44_20260122_09de6e7.img
P1_AIR_VENDOR_SITE = https://drive.usercontent.google.com
P1_AIR_VENDOR_LICENSE = PROPRIETARY
P1_AIR_VENDOR_REDISTRIBUTE = NO
P1_AIR_VENDOR_DEPENDENCIES = host-python3 host-lzo host-squashfs host-riscv64-zephyr-elf-toolchain
P1_AIR_VENDOR_INSTALL_TARGET = NO
P1_AIR_VENDOR_INSTALL_IMAGES = YES
P1_AIR_VENDOR_ADD_TOOLCHAIN_DEPENDENCY = NO
P1_AIR_VENDOR_DOWNLOAD_DEPENDENCIES = host-python3

# Drive requires a confirmation query that Buildroot's filename-based wget
# backend cannot represent. Populate its normal cache atomically, then let
# the standard download step verify the .hash file as usual.
define P1_AIR_VENDOR_FETCH
	mkdir -p $(P1_AIR_VENDOR_DL_DIR)
	flock $(P1_AIR_VENDOR_DL_DIR)/.p1-fetch.lock \
		$(HOST_DIR)/bin/python3 $(P1_AIR_VENDOR_PKGDIR)/fetch.py \
		$(P1_AIR_VENDOR_DL_DIR)/$(P1_AIR_VENDOR_SOURCE) \
		--wget '$(call qstrip,$(BR2_WGET))'
endef
P1_AIR_VENDOR_PRE_DOWNLOAD_HOOKS += P1_AIR_VENDOR_FETCH

define P1_AIR_VENDOR_EXTRACT_CMDS
	cp '$(P1_AIR_VENDOR_DL_DIR)/$(P1_AIR_VENDOR_SOURCE)' $(@D)/stock.img
endef

define P1_AIR_VENDOR_BUILD_CMDS
	$(HOST_DIR)/bin/python3 $(P1_AIR_VENDOR_PKGDIR)/extract.py \
		--image $(@D)/stock.img --output $(@D)/stock \
		--liblzo $(HOST_DIR)/lib/liblzo2.so \
		--unsquashfs $(HOST_DIR)/bin/unsquashfs
	$(HOST_DIR)/bin/unsquashfs -cat $(@D)/stock/root.squashfs \
		usr/usrdata/ar813x/bb_demo_air_d.img > $(@D)/stock/radio.img
	$(HOST_DIR)/bin/python3 $(P1_AIR_VENDOR_PKGDIR)/generate-radio-profile.py \
		--radio $(@D)/stock/radio.img --output $(@D)/stock/p1-air.c \
		--tool-prefix $(HOST_RISCV64_ZEPHYR_ELF_TOOLCHAIN_INSTALL_DIR)/bin/riscv64-zephyr-elf-
endef

define P1_AIR_VENDOR_INSTALL_IMAGES_CMDS
	mkdir -p $(BINARIES_DIR)/p1-air-stock
	cp $(@D)/stock/*.json $(@D)/stock/*.squashfs $(BINARIES_DIR)/p1-air-stock/
endef

$(eval $(generic-package))
