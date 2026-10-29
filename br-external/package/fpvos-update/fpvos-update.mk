################################################################################
#
# fpvos-update
#
################################################################################

FPVOS_UPDATE_VERSION = 1
FPVOS_UPDATE_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/fpvos-update
FPVOS_UPDATE_SITE_METHOD = local
FPVOS_UPDATE_LICENSE = GPL-2.0-or-later
FPVOS_UPDATE_LICENSE_FILES = src/COPYING
FPVOS_UPDATE_DEPENDENCIES = busybox
FPVOS_UPDATE_INSTALL_IMAGES = YES

ifeq ($(BR2_PACKAGE_FPVOS_UPDATE_AR9311),y)
FPVOS_UPDATE_BOARD = ar9311
endif

define FPVOS_UPDATE_BUILD_CMDS
	python3 $(@D)/generate-profile.py $(@D)/backends/$(FPVOS_UPDATE_BOARD)/profile.json $(@D)/profile.c
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror -I$(@D)/src \
		-Dmain=fpvos_receiver_main -c $(@D)/src/receiver.c -o $(@D)/receiver.o
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror -I$(@D)/src \
		-Dmain=fpvos_verify_main -c $(@D)/src/verify.c -o $(@D)/verify.o
	$(FPVOS_UPDATE_BUILD_BACKEND_CMDS)
	python3 $(FPVOS_UPDATE_SITE)/embed-bootstrap.py $(TARGET_DIR)/bin/busybox \
		$(FPVOS_UPDATE_SITE) $(@D)/bootstrap-resources.c
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror -I$(@D)/src \
		$(@D)/src/main.c $(@D)/src/bootstrap.c $(@D)/bootstrap-resources.c \
		$(@D)/receiver.o $(@D)/verify.o $(@D)/nand.o \
		$(@D)/profile.c $(@D)/backends/$(FPVOS_UPDATE_BOARD)/images.c \
		$(TARGET_LDFLAGS) -static -o $(@D)/fpvos-update
	$(TARGET_STRIP) --remove-section=.comment --remove-section=.note $(@D)/fpvos-update
endef

define FPVOS_UPDATE_INSTALL_TARGET_CMDS
	$(FPVOS_UPDATE_INSTALL_BACKEND_CMDS)
	$(INSTALL) -D -m 0755 $(@D)/src/run-receiver $(TARGET_DIR)/usr/sbin/fpvos-update-service
	$(INSTALL) -D -m 0755 $(@D)/fpvos-update $(TARGET_DIR)/usr/sbin/fpvos-update
	ln -sf fpvos-update $(TARGET_DIR)/usr/sbin/fpvos-update-receiver
	ln -sf ../sbin/fpvos-update $(TARGET_DIR)/usr/libexec/fpvos-update-verify
endef

define FPVOS_UPDATE_INSTALL_IMAGES_CMDS
	$(INSTALL) -D -m 0755 $(@D)/fpvos-update $(BINARIES_DIR)/fpvos-update-ar9311
	$(INSTALL) -D -m 0755 $(FPVOS_UPDATE_SITE)/backends/ar9311/bootstrap.sh \
		$(BINARIES_DIR)/fpvos-ar9311-bootstrap.sh
	# Remove the superseded artifact produced by older versions of this package.
	rm -f $(BINARIES_DIR)/fpvos-ar9311-bootstrap.tar
endef

$(eval $(generic-package))

# Include backend command hooks after generic-package: Buildroot derives the
# package name from the last parsed makefile's directory.
ifeq ($(BR2_PACKAGE_FPVOS_UPDATE_AR9311),y)
include $(FPVOS_UPDATE_SITE)/backends/ar9311/backend.mk
endif
