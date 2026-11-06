################################################################################
#
# ar9311-camera-control
#
################################################################################

AR9311_CAMERA_CONTROL_VERSION = 674ec00ecde0bba2eb844def1b4a0b7f8e685e13
AR9311_CAMERA_CONTROL_SITE = $(call github,Missing-Lynk,ml-userspace,$(AR9311_CAMERA_CONTROL_VERSION))
AR9311_CAMERA_CONTROL_LICENSE = GPL-3.0
AR9311_CAMERA_CONTROL_LICENSE_FILES = LICENSE

define AR9311_CAMERA_CONTROL_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) $(TARGET_LDFLAGS) -I$(AR9311_CAMERA_CONTROL_PKGDIR) -o $(@D)/ar9311-aed \
		$(@D)/ml-aed/ml-aed.c $(@D)/ml-aed/ml-aed-core.c \
		$(@D)/ml-aed/ml-aed-tuning.c -lm
	$(TARGET_CC) $(TARGET_CFLAGS) $(TARGET_LDFLAGS) -Wall -Wextra \
		-o $(@D)/ar9311-awbd $(AR9311_CAMERA_CONTROL_PKGDIR)/awbd.c \
		$(AR9311_CAMERA_CONTROL_PKGDIR)/awb.c -lm
endef

define AR9311_CAMERA_CONTROL_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(AR9311_CAMERA_CONTROL_PKGDIR)/ar9311-camera-record \
		$(TARGET_DIR)/usr/bin/ar9311-camera-record
	$(INSTALL) -D -m 0755 $(@D)/ar9311-aed $(TARGET_DIR)/usr/bin/ar9311-aed
	$(INSTALL) -D -m 0755 $(@D)/ar9311-awbd $(TARGET_DIR)/usr/bin/ar9311-awbd
endef

$(eval $(generic-package))
