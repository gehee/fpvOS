################################################################################
#
# ps5280  (GT sensor glue; the stock air app keeps the CMOS driver)
#
################################################################################

PS5280_VERSION = 1
PS5280_SITE = $(PS5280_PKGDIR)
PS5280_SITE_METHOD = local
PS5280_LICENSE = MIT

define PS5280_BUILD_CMDS
	$(TARGET_CC) -shared -fPIC -O2 -Wall -Wextra \
		-Wl,-soname,libsns_ps5280.so \
		-o $(@D)/libsns_ps5280.so $(@D)/libsns_ps5280.c
endef

define PS5280_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/libsns_ps5280.so \
		$(TARGET_DIR)/usrdata/fpv/air/lib/libsns_ps5280.so
endef

$(eval $(generic-package))
