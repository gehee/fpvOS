################################################################################
#
# ar9311-temp
#
################################################################################

AR9311_TEMP_VERSION = 1
AR9311_TEMP_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/ar9311-temp/src
AR9311_TEMP_SITE_METHOD = local
AR9311_TEMP_LICENSE = GPL-2.0-or-later
AR9311_TEMP_MODULE_SUBDIRS = .

$(eval $(kernel-module))
$(eval $(generic-package))
