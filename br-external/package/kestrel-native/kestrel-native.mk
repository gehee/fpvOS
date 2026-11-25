################################################################################
#
# kestrel-native
#
################################################################################

KESTREL_NATIVE_VERSION = 1
KESTREL_NATIVE_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/kestrel-common
KESTREL_NATIVE_SITE_METHOD = local
KESTREL_NATIVE_LICENSE = MIT (supervisor), GPL-3.0 (runtime)
# kestrel-common has no licence file: the supervisor's SPDX header is its licence.
KESTREL_NATIVE_LICENSE_FILES = supervise.c

# Prepared by tools/package_ascent.py in the ground repository. It contains
# static target executables and host-baked assets, with no machine settings.
# KESTREL_NATIVE_SHA256 (on the make line or in the environment), when set,
# pins the image: any other file fails the build. Pinned or not, the image
# records what it carries in /usr/share/kestrel/runtime.sha256.
define KESTREL_NATIVE_BUILD_CMDS
	test -s "$(KESTREL_NATIVE_IMAGE)" || \
		{ echo "Set KESTREL_NATIVE_IMAGE to the packaged board runtime" >&2; exit 1; }
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror $(TARGET_LDFLAGS) \
		$(@D)/supervise.c -o $(@D)/kestrel-gnd-supervise
endef

# Checked at install, so kestrel-native-reinstall checks a replaced image too:
# the file before it is copied, and the copy itself before its sum is recorded.
define KESTREL_NATIVE_CHECK_IMAGE
	sum=$$(sha256sum "$(1)" | cut -d' ' -f1) && \
	pin=$$(printf '%s' "$(KESTREL_NATIVE_SHA256)" | tr A-F a-f) && \
	if [ -n "$$pin" ] && [ "$$sum" != "$$pin" ]; then \
		echo "$(1): sha256 $$sum, not KESTREL_NATIVE_SHA256 $$pin" >&2; \
		exit 1; \
	fi
endef

define KESTREL_NATIVE_INSTALL_TARGET_CMDS
	$(call KESTREL_NATIVE_CHECK_IMAGE,$(KESTREL_NATIVE_IMAGE))
	$(INSTALL) -D -m 0644 "$(KESTREL_NATIVE_IMAGE)" $(TARGET_DIR)/usr/share/kestrel/runtime.squashfs
	$(call KESTREL_NATIVE_CHECK_IMAGE,$(TARGET_DIR)/usr/share/kestrel/runtime.squashfs) && \
	printf '%s  runtime.squashfs\n' "$$sum" > $(TARGET_DIR)/usr/share/kestrel/runtime.sha256
	chmod 0644 $(TARGET_DIR)/usr/share/kestrel/runtime.sha256
	$(INSTALL) -D -m 0755 $(@D)/kestrel-gnd-supervise $(TARGET_DIR)/usr/sbin/kestrel-gnd-supervise
	$(INSTALL) -D -m 0755 $(KESTREL_NATIVE_PKGDIR)/run $(TARGET_DIR)/usr/bin/kestrel-gnd-run
	$(INSTALL) -D -m 0755 $(KESTREL_NATIVE_PKGDIR)/S60kestrel-gnd $(TARGET_DIR)/etc/init.d/S60kestrel-gnd
endef

$(eval $(generic-package))
