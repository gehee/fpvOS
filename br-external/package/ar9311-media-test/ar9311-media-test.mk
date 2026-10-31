################################################################################
#
# ar9311-media-test
#
################################################################################

AR9311_MEDIA_TEST_VERSION = 1
AR9311_MEDIA_TEST_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/ar9311-media-test/src
AR9311_MEDIA_TEST_SITE_METHOD = local
AR9311_MEDIA_TEST_LICENSE = MIT
AR9311_MEDIA_TEST_LICENSE_FILES = LICENSE

define AR9311_MEDIA_TEST_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror \
		$(@D)/decode-test.c $(@D)/decode.c $(TARGET_LDFLAGS) -o $(@D)/ar9311-decode-test
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror \
		$(@D)/play.c $(@D)/decode.c $(TARGET_LDFLAGS) -o $(@D)/ar9311-play
endef

define AR9311_MEDIA_TEST_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/ar9311-decode-test \
		$(TARGET_DIR)/usr/bin/ar9311-decode-test
	$(INSTALL) -D -m 0755 $(@D)/ar9311-play $(TARGET_DIR)/usr/bin/ar9311-play
endef

$(eval $(generic-package))
