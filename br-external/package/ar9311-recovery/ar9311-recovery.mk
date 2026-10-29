################################################################################
#
# ar9311-recovery
#
################################################################################

AR9311_RECOVERY_VERSION = 1
AR9311_RECOVERY_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/ar9311-recovery/src
AR9311_RECOVERY_SITE_METHOD = local
AR9311_RECOVERY_LICENSE = GPL-2.0-or-later
AR9311_RECOVERY_LICENSE_FILES = COPYING
AR9311_RECOVERY_DEPENDENCIES = busybox dropbear fpvos-update host-mkpasswd

define AR9311_RECOVERY_BUILD_CMDS
	python3 $(@D)/build-root.py \
		$(TARGET_DIR) $(@D)/root $(BUSYBOX_DIR)/busybox.links \
		$(TARGET_STRIP) $(HOST_DIR)/bin/mkpasswd \
		$(BR2_EXTERNAL_FPVOS_PATH)/board/ar9311/rootfs-overlay
endef

$(eval $(generic-package))
