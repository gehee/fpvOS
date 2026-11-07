################################################################################
#
# fpvos-usb  (fpvOS_usb: USB modes and the AR8030 bridge)
#
################################################################################

# Pinned to a commit, never a branch (see ../kestrel/kestrel.mk for why).
# FPVOS_USB_OVERRIDE_SRCDIR=/path/to/fpvOS_usb builds a local checkout instead.
FPVOS_USB_SITE ?= https://github.com/gehee/fpvOS_usb.git
FPVOS_USB_SITE_METHOD = git
FPVOS_USB_VERSION ?= 8ba24ff4515502adac25de6a34592265a287f078
FPVOS_USB_LICENSE = GPL-2.0-or-later
FPVOS_USB_LICENSE_FILES = LICENSE
FPVOS_USB_BOARD = $(call qstrip,$(BR2_PACKAGE_FPVOS_USB_BOARD))

define FPVOS_USB_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) CC="$(TARGET_CC)" CFLAGS="$(TARGET_CFLAGS)" \
		LDFLAGS="$(TARGET_LDFLAGS)" fpvos-usb
endef

ifeq ($(FPVOS_USB_BOARD),ascent-lite)
# The Lite and Lite+ keep the stock rootfs (read-only), so everything goes in
# the app volume, in air/usb/: the program, the hooks and both boards'
# settings, the Lite's and the Lite+'s, which air/fpvos-usb picks between.
FPVOS_USB_APP = $(TARGET_DIR)/usrdata/fpv/air/usb
define FPVOS_USB_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/fpvos-usb $(FPVOS_USB_APP)/fpvos-usb
	for board in ascent-lite ascent-lite-plus; do \
		$(INSTALL) -D -m 0644 $(@D)/boards/$$board/fpvos-usb.conf \
			$(FPVOS_USB_APP)/$$board.conf || exit 1; \
	done
	for hook in radio-stop chip-load radio-start; do \
		$(INSTALL) -D -m 0755 $(@D)/boards/ascent-lite/$$hook \
			$(FPVOS_USB_APP)/$$hook || exit 1; \
	done
endef
else
define FPVOS_USB_INSTALL_TARGET_CMDS
	test -d $(@D)/boards/$(FPVOS_USB_BOARD)
	$(INSTALL) -D -m 0755 $(@D)/fpvos-usb $(TARGET_DIR)/usr/sbin/fpvos-usb
	$(INSTALL) -D -m 0644 $(@D)/boards/$(FPVOS_USB_BOARD)/fpvos-usb.conf \
		$(TARGET_DIR)/etc/default/fpvos-usb
	for hook in radio-stop chip-load radio-start; do \
		$(INSTALL) -D -m 0755 $(@D)/boards/$(FPVOS_USB_BOARD)/$$hook \
			$(TARGET_DIR)/usr/libexec/fpvos-usb/$$hook || exit 1; \
	done
endef
endif

$(eval $(generic-package))
