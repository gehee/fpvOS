# AR9311-specific storage implementation and installed helper.
define FPVOS_UPDATE_BUILD_BACKEND_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror \
		-Dmain=fpvos_nand_main -c $(@D)/backends/ar9311/nand.c -o $(@D)/nand.o
endef

define FPVOS_UPDATE_INSTALL_BACKEND_CMDS
	ln -sf fpvos-update $(TARGET_DIR)/usr/sbin/ar9311-nandctl
	$(INSTALL) -D -m 0755 $(@D)/backends/ar9311/update-helper $(TARGET_DIR)/usr/libexec/fpvos-update-backend
endef
