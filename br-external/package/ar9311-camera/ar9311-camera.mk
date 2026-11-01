################################################################################
#
# ar9311-camera
#
################################################################################

AR9311_CAMERA_VERSION = 1
AR9311_CAMERA_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/ar9311-camera/src
AR9311_CAMERA_SITE_METHOD = local
AR9311_CAMERA_LICENSE = GPL-2.0-only
AR9311_CAMERA_LICENSE_FILES = COPYING

$(eval $(kernel-module))
$(eval $(generic-package))
