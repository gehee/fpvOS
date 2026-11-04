# Static libfdt is built from Buildroot's pinned host-dtc source. The target dtc
# package excludes static-only toolchains; the RAM recovery agent needs no loader.
FPVOS_UPDATE_BACKEND_LINK = $(@D)/p1-storage.o $(@D)/p1-flash.o \
	-I$(HOST_DTC_DIR)/libfdt $(@D)/p1-libfdt-*.o

define FPVOS_UPDATE_BUILD_BACKEND_CMDS
	for source in $(HOST_DTC_DIR)/libfdt/*.c; do \
		$(TARGET_CC) $(TARGET_CFLAGS) -I$(HOST_DTC_DIR)/libfdt -c "$$source" \
		-o "$(@D)/p1-libfdt-$$(basename "$$source" .c).o" || exit 1; \
	done
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror -I$(@D)/src \
		-Dmain=fpvos_nand_main -c $(@D)/backends/p1-air/nand.c -o $(@D)/nand.o
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror -I$(@D)/src \
		-c $(@D)/backends/p1-air/storage.c -o $(@D)/p1-storage.o
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror -I$(@D)/src \
		-c $(@D)/backends/p1-air/flash.c -o $(@D)/p1-flash.o
endef

define FPVOS_UPDATE_INSTALL_BACKEND_CMDS
	$(INSTALL) -D -m 0755 $(@D)/backends/p1-air/update-helper $(TARGET_DIR)/usr/libexec/fpvos-update-backend
	rm -f $(TARGET_DIR)/etc/init.d/S70p1-boot
	ln -sf fpvos-update $(TARGET_DIR)/usr/sbin/ar9311-nandctl
endef
