################################################################################
#
# fpvos-recovery
#
################################################################################

FPVOS_RECOVERY_VERSION = 1
FPVOS_RECOVERY_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/fpvos-recovery/src
FPVOS_RECOVERY_SITE_METHOD = local
FPVOS_RECOVERY_LICENSE = GPL-2.0-or-later
FPVOS_RECOVERY_LICENSE_FILES = COPYING
FPVOS_RECOVERY_DEPENDENCIES = busybox dropbear fpvos-update host-mkpasswd

define FPVOS_RECOVERY_BUILD_CMDS
	python3 $(@D)/build-root.py \
		$(TARGET_DIR) $(@D)/root $(BUSYBOX_DIR)/busybox.links \
		$(TARGET_STRIP) $(HOST_DIR)/bin/mkpasswd \
		$(FPVOS_UPDATE_SITE)/backends/$(FPVOS_UPDATE_BOARD)/profile.json \
		$(call qstrip,$(BR2_ROOTFS_OVERLAY))
endef

$(eval $(generic-package))
