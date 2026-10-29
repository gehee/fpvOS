################################################################################
#
# ar9311-radio
#
################################################################################

AR9311_RADIO_VERSION = 1
AR9311_RADIO_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/ar9311-radio/src
AR9311_RADIO_SITE_METHOD = local
AR9311_RADIO_LICENSE = GPL-2.0-or-later (kernel module), GPL-3.0 (client)
AR9311_RADIO_LICENSE_FILES = LICENSE COPYING.GPL3
AR9311_RADIO_DEPENDENCIES = ar-libre open8030 ar9311-mmc
AR9311_RADIO_MODULE_SUBDIRS = .

define AR9311_RADIO_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror \
		$(@D)/radio.c $(@D)/sky.c $(TARGET_LDFLAGS) -lar8030_client -pthread -o $(@D)/ar9311-radio
endef

define AR9311_RADIO_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/ar9311-radio $(TARGET_DIR)/usr/bin/ar9311-radio
	$(INSTALL) -D -m 0755 $(@D)/S44ar9311-radio $(TARGET_DIR)/etc/init.d/S44ar9311-radio
endef

$(eval $(kernel-module))
$(eval $(generic-package))
