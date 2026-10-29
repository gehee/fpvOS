################################################################################
#
# ascent-gnd485-recovery
#
################################################################################

ASCENT_GND485_RECOVERY_VERSION = 1
ASCENT_GND485_RECOVERY_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/ascent-gnd485-recovery/src
ASCENT_GND485_RECOVERY_SITE_METHOD = local
ASCENT_GND485_RECOVERY_LICENSE = GPL-2.0-or-later
ASCENT_GND485_RECOVERY_LICENSE_FILES = COPYING
ASCENT_GND485_RECOVERY_DEPENDENCIES = busybox dropbear fpvos-update host-mkpasswd

define ASCENT_GND485_RECOVERY_BUILD_CMDS
	python3 $(@D)/build-root.py \
		$(TARGET_DIR) $(@D)/root $(BUSYBOX_DIR)/busybox.links \
		$(TARGET_STRIP) $(HOST_DIR)/bin/mkpasswd \
		$(BR2_EXTERNAL_FPVOS_PATH)/board/ascent-gnd485/rootfs-overlay
endef

$(eval $(generic-package))
