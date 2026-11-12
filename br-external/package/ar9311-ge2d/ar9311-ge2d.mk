################################################################################
#
# ar9311-ge2d
#
################################################################################

AR9311_GE2D_VERSION = 1
AR9311_GE2D_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/ar9311-ge2d/src
AR9311_GE2D_SITE_METHOD = local
AR9311_GE2D_LICENSE = GPL-2.0-or-later
AR9311_GE2D_MODULE_SUBDIRS = .
AR9311_GE2D_INSTALL_STAGING = YES

define AR9311_GE2D_INSTALL_STAGING_CMDS
	$(INSTALL) -D -m 0644 $(@D)/ar9311_ge2d.h $(STAGING_DIR)/usr/include/linux/ar9311_ge2d.h
endef

$(eval $(kernel-module))
$(eval $(generic-package))
