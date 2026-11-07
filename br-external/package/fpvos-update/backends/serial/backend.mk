# Boards updated another way: the receiver, the verifier and stubs.c; no
# NAND tool and no embedded bootstrap.
FPVOS_UPDATE_PROFILE = $(@D)/backends/serial/$(FPVOS_UPDATE_BOARD).json
FPVOS_UPDATE_BOARD_SRCS = $(@D)/backends/serial/stubs.c

define FPVOS_UPDATE_INSTALL_BACKEND_CMDS
	$(INSTALL) -D -m 0755 $(@D)/backends/serial/update-helper $(TARGET_DIR)/usr/libexec/fpvos-update-backend
endef
