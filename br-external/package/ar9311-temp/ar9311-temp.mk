################################################################################
#
# ar9311-temp
#
################################################################################

AR9311_TEMP_VERSION = 1
AR9311_TEMP_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/ar9311-temp/src
AR9311_TEMP_SITE_METHOD = local
AR9311_TEMP_LICENSE = GPL-2.0-or-later
# No licence file in src/: the driver's SPDX header is its licence statement.
AR9311_TEMP_LICENSE_FILES = ar9311_temp.c
AR9311_TEMP_MODULE_SUBDIRS = .

$(eval $(kernel-module))
$(eval $(generic-package))
