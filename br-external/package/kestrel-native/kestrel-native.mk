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

# The board's runtime: static target executables and host-baked assets, no
# machine settings. scripts/native-runtime.sh builds it from KESTREL_PIN and
# AR_LIBRE_VERSION into output/kestrel-runtime/ (build.sh runs it when the
# file there is not the pinned one). The P1 ground units (goggles, the Nano
# VRX on its own image too, and the combined p1-gnd image) have their own
# (its P1 panel reads their adc-keys); the Ascent VRX and the SteadyDigital
# share the ascent one.
KESTREL_NATIVE_BOARD = $(if $(BR2_FPVOS_BOARD_P1_GOGGLE)$(BR2_FPVOS_BOARD_P1_GND)$(BR2_FPVOS_BOARD_P1_NANO_VRX),p1goggle,ascent)
KESTREL_NATIVE_IMAGE ?= $(BR2_EXTERNAL_FPVOS_PATH)/../output/kestrel-runtime/runtime-$(KESTREL_NATIVE_BOARD).squashfs

# The pin: the runtime the pins build, in runtime.hash (board, sha256,
# kestrel-gnd, ar_libre). Any other file fails the build. A line that names
# other pins than the tree's fails it too: KESTREL_PIN or AR_LIBRE_VERSION
# moved without a new runtime. KESTREL_NATIVE_SHA256 set (make line or
# environment) replaces the pin, empty for none - a development runtime of
# your own in KESTREL_NATIVE_IMAGE. Pinned or not, the image records what it
# carries in /usr/share/kestrel/runtime.sha256.
KESTREL_NATIVE_PIN_LINE = $(shell awk '$$1 == "$(KESTREL_NATIVE_BOARD)"' $(KESTREL_NATIVE_PKGDIR)/runtime.hash)
KESTREL_NATIVE_SHA256 ?= $(word 2,$(KESTREL_NATIVE_PIN_LINE))
KESTREL_NATIVE_PINNED = $(if $(filter environment command line,$(origin KESTREL_NATIVE_SHA256)),,y)

define KESTREL_NATIVE_BUILD_CMDS
	test -s "$(KESTREL_NATIVE_IMAGE)" || \
		{ echo "$(KESTREL_NATIVE_IMAGE): no runtime - scripts/native-runtime.sh $(KESTREL_NATIVE_BOARD) builds it" >&2; exit 1; }
	test -z "$(KESTREL_NATIVE_PINNED)" || \
	test "$(word 3,$(KESTREL_NATIVE_PIN_LINE))" = "$(KESTREL_PIN)" -a "$(word 4,$(KESTREL_NATIVE_PIN_LINE))" = "$(AR_LIBRE_VERSION)" || \
		{ echo "kestrel-native: runtime.hash pins $(KESTREL_NATIVE_BOARD) for kestrel-gnd $(word 3,$(KESTREL_NATIVE_PIN_LINE)) and ar_libre $(word 4,$(KESTREL_NATIVE_PIN_LINE)) - not KESTREL_PIN $(KESTREL_PIN) and AR_LIBRE_VERSION $(AR_LIBRE_VERSION): rebuild both runtimes with scripts/native-runtime.sh and update runtime.hash" >&2; exit 1; }
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
	$(INSTALL) -D -m 0755 $(KESTREL_NATIVE_PKGDIR)/S46kestrel-state-ubifs $(TARGET_DIR)/etc/init.d/S46kestrel-state
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

# A new runtime file is installed again: no reinstall to remember.
$(KESTREL_NATIVE_TARGET_INSTALL_TARGET): $(wildcard $(KESTREL_NATIVE_IMAGE))
