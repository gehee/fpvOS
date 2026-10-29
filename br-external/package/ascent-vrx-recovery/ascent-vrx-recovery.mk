################################################################################
#
# ascent-vrx-recovery
#
################################################################################

ASCENT_VRX_RECOVERY_VERSION = 1
ASCENT_VRX_RECOVERY_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/ascent-vrx-recovery/src
ASCENT_VRX_RECOVERY_SITE_METHOD = local
ASCENT_VRX_RECOVERY_LICENSE = GPL-2.0-or-later
ASCENT_VRX_RECOVERY_LICENSE_FILES = COPYING
ASCENT_VRX_RECOVERY_DEPENDENCIES = busybox dropbear fpvos-update host-mkpasswd

define ASCENT_VRX_RECOVERY_BUILD_CMDS
	python3 $(@D)/build-root.py \
		$(TARGET_DIR) $(@D)/root $(BUSYBOX_DIR)/busybox.links \
		$(TARGET_STRIP) $(HOST_DIR)/bin/mkpasswd \
		$(BR2_EXTERNAL_FPVOS_PATH)/board/ascent-vrx/rootfs-overlay
endef

$(eval $(generic-package))
