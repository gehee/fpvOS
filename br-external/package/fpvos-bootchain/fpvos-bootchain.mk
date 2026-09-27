################################################################################
# fpvos-bootchain
#
# The SD card's boot chain, built from the stock boot images the user's own
# firmware holds (vendor/stock/, from scripts/extract-vendor.py). All of what
# fpvOS changes - three U-Boot stubs, the SD-card device tree - is in
# boot/mkbootchain.py; nothing prebuilt is shipped or needed.
################################################################################

FPVOS_BOOTCHAIN_VERSION = 1.0
FPVOS_BOOTCHAIN_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/../vendor/stock
FPVOS_BOOTCHAIN_SITE_METHOD = local
# dtc and lz4 only: the FIT is built with dtc (see mkbootchain.py), since
# host-uboot-tools pulls in gnutls, which fails on current distributions.
FPVOS_BOOTCHAIN_DEPENDENCIES = host-dtc host-lz4
FPVOS_BOOTCHAIN_INSTALL_TARGET = NO
FPVOS_BOOTCHAIN_INSTALL_IMAGES = YES

FPVOS_BOOTCHAIN_FILES = uboot-patched.bin boot-sd3.img rk3568-pro-patched.dtb Image

define FPVOS_BOOTCHAIN_BUILD_CMDS
	python3 $(BR2_EXTERNAL_FPVOS_PATH)/../boot/mkbootchain.py \
		--stock $(@D) \
		--its $(BR2_EXTERNAL_FPVOS_PATH)/../boot/sd3.its \
		--out $(@D)/out \
		--dtc $(HOST_DIR)/bin/dtc \
		--lz4 $(HOST_DIR)/bin/lz4
endef

define FPVOS_BOOTCHAIN_INSTALL_IMAGES_CMDS
	$(foreach f,$(FPVOS_BOOTCHAIN_FILES),
		$(INSTALL) -D -m 0644 $(@D)/out/$(f) $(BINARIES_DIR)/$(f)
	)
endef

$(eval $(generic-package))
