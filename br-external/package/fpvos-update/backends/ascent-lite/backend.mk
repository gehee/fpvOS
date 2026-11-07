# The Ascent Lite / Lite+ (stock kernel and rootfs, fpvOS's app volume): the
# receiver as the stock updater, at its path in the app volume, so the stock
# rootfs starts it in the normal and the clean system. lite.c writes the
# flash itself: no NAND tool and no embedded bootstrap.
FPVOS_UPDATE_BOARD_SRCS = $(@D)/backends/ascent-lite/lite.c
FPVOS_UPDATE_EMBED_CMDS =
FPVOS_UPDATE_INSTALL_BOOTSTRAP_CMDS =

define FPVOS_UPDATE_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/fpvos-update $(TARGET_DIR)/usrdata/fpv/ar_fpvhs_upgrade
endef
