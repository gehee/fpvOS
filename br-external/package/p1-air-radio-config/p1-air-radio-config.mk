################################################################################
#
# p1-air-radio-config
#
################################################################################

P1_AIR_RADIO_CONFIG_VERSION = 1
P1_AIR_RADIO_CONFIG_SOURCE =
P1_AIR_RADIO_CONFIG_LICENSE = PROPRIETARY
P1_AIR_RADIO_CONFIG_REDISTRIBUTE = NO
P1_AIR_RADIO_CONFIG_DEPENDENCIES = p1-air-vendor host-python3 host-squashfs

define P1_AIR_RADIO_CONFIG_BUILD_CMDS
	$(HOST_DIR)/bin/unsquashfs -cat $(P1_AIR_VENDOR_DIR)/stock/root.squashfs \
		usr/usrdata/ar813x/bb_config_air.json > $(@D)/stock.json
	$(HOST_DIR)/bin/python3 $(P1_AIR_RADIO_CONFIG_PKGDIR)/configure.py \
		$(@D)/stock.json $(@D)/base.json
endef

define P1_AIR_RADIO_CONFIG_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/base.json $(TARGET_DIR)/usr/share/radio/p1-air.json
	mkdir -p $(TARGET_DIR)/lib/firmware
	ln -sf /run/ar9311-radio/config.json $(TARGET_DIR)/lib/firmware/p1-air-radio.json
endef

$(eval $(generic-package))
