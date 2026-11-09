################################################################################
#
# kestrel-native
#
################################################################################

KESTREL_NATIVE_VERSION = 1
KESTREL_NATIVE_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/kestrel-common
KESTREL_NATIVE_SITE_METHOD = local
KESTREL_NATIVE_LICENSE = MIT (supervisor), GPL-3.0 (runtime)

# Prepared by tools/package_ascent.py in the ground repository. It contains
# static target executables and host-baked assets, with no machine settings.
define KESTREL_NATIVE_BUILD_CMDS
	test -s "$(KESTREL_NATIVE_IMAGE)" || \
		{ echo "Set KESTREL_NATIVE_IMAGE to the packaged Ascent runtime" >&2; exit 1; }
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror $(TARGET_LDFLAGS) \
		$(@D)/supervise.c -o $(@D)/kestrel-gnd-supervise
endef

define KESTREL_NATIVE_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(KESTREL_NATIVE_IMAGE) $(TARGET_DIR)/usr/share/kestrel/runtime.squashfs
	$(INSTALL) -D -m 0755 $(@D)/kestrel-gnd-supervise $(TARGET_DIR)/usr/sbin/kestrel-gnd-supervise
	$(INSTALL) -D -m 0755 $(KESTREL_NATIVE_PKGDIR)/run $(TARGET_DIR)/usr/bin/kestrel-gnd-run
	$(INSTALL) -D -m 0755 $(KESTREL_NATIVE_PKGDIR)/S60kestrel-gnd $(TARGET_DIR)/etc/init.d/S60kestrel-gnd
endef

$(eval $(generic-package))
