################################################################################
#
# open8030
#
################################################################################

# Radio-chip firmware, independent of the Linux host SoC or application.
# Board defconfigs select profile, transport, role and factory-data policy.
OPEN8030_VERSION ?= 89d3c634c11d5665dcc17401c5d8b3172bbacf8b
OPEN8030_SITE ?= https://github.com/gehee/Open8030.git
OPEN8030_SITE_METHOD = git
OPEN8030_PROFILE = $(call qstrip,$(BR2_PACKAGE_OPEN8030_PROFILE))
OPEN8030_CONFIG ?= $(call qstrip,$(BR2_PACKAGE_OPEN8030_CONFIG))

# Bare filenames come from the published archive; absolute paths name private
# inputs. Keep make-time directory overrides for profile/config development:
# OPEN8030_PRIVATE_DIR (scripts/open8030-private.sh fills it with the profiles
# and the ground radio config) overrides both, OPEN8030_CONFIG_DIR the config.
OPEN8030_CONFIG_DIR ?= $(OPEN8030_PRIVATE_DIR)
OPEN8030_PROFILE_SOURCE = $(if $(OPEN8030_PRIVATE_DIR),$(OPEN8030_PRIVATE_DIR)/$(notdir $(OPEN8030_PROFILE)),$(if $(filter /%,$(OPEN8030_PROFILE)),$(OPEN8030_PROFILE),$(OPEN8030_PROFILES_DIR)/$(OPEN8030_PROFILE)))
OPEN8030_CONFIG_SOURCE = $(if $(OPEN8030_CONFIG_DIR),$(OPEN8030_CONFIG_DIR)/$(notdir $(OPEN8030_CONFIG)),$(if $(filter /%,$(OPEN8030_CONFIG)),$(OPEN8030_CONFIG),$(OPEN8030_PROFILES_DIR)/$(OPEN8030_CONFIG)))
OPEN8030_DEPENDENCIES = open8030-profiles
OPEN8030_IMAGE = open8030.img
OPEN8030_CFLAGS =

ifeq ($(BR2_PACKAGE_OPEN8030_TRANSPORT_USB),y)
OPEN8030_CFLAGS += -DAR_FORCE_USB
endif
# SDIO retains upstream active-bus detection, matching the existing images.
ifeq ($(BR2_PACKAGE_OPEN8030_ROLE_AP),y)
OPEN8030_CFLAGS += -DAR_ROLE_AP
OPEN8030_DEST = /usrdata/fpv/air/open8030
else
OPEN8030_DEST = /lib/firmware
endif
ifeq ($(BR2_PACKAGE_OPEN8030_FACTORY_OPTIONAL),y)
OPEN8030_CFLAGS += -DAR_FACTORY_OPTIONAL
endif

# Zephyr's kernel and the compiler's runtime are compiled into the image.
OPEN8030_LICENSE = MIT, Apache-2.0 (Zephyr), GPL-3.0+ with GCC runtime exception (libgcc)
OPEN8030_LICENSE_FILES = LICENSE THIRD_PARTY.md
# Firmware for the radio chip: the target's toolchain is not used.
OPEN8030_ADD_TOOLCHAIN_DEPENDENCY = NO
OPEN8030_DEPENDENCIES += \
	host-riscv64-zephyr-elf-toolchain host-zephyr host-zephyr-python \
	host-ninja $(BR2_CMAKE_HOST_DEPENDENCY)

# The --cflags= form accepts flag values starting with -D.
define OPEN8030_BUILD_CMDS
	test -n "$(OPEN8030_PROFILE)" && test -f "$(OPEN8030_PROFILE_SOURCE)" || \
		{ echo "Missing Open8030 profile: $(OPEN8030_PROFILE_SOURCE); set BR2_PACKAGE_OPEN8030_PROFILE or OPEN8030_PRIVATE_DIR" >&2; exit 1; }
	$(if $(BR2_PACKAGE_OPEN8030_ROLE_AP),,test -f "$(OPEN8030_CONFIG_SOURCE)" || \
		{ echo "Missing Open8030 radio config: $(OPEN8030_CONFIG_SOURCE); set BR2_PACKAGE_OPEN8030_CONFIG or OPEN8030_CONFIG_DIR" >&2; exit 1; })
	cd $(@D) && $(HOST_MAKE_ENV) USER_CACHE_DIR=$(@D)/build/cache \
		$(HOST_DIR)/bin/python3 ./open8030 image \
		--profile "$(OPEN8030_PROFILE_SOURCE)" \
		--output $(@D)/$(OPEN8030_IMAGE) \
		--cflags="$(OPEN8030_CFLAGS)" \
		--zephyr $(HOST_ZEPHYR_WORKSPACE)/zephyr \
		--toolchain $(HOST_RISCV64_ZEPHYR_ELF_TOOLCHAIN_INSTALL_DIR) \
		--python $(HOST_DIR)/bin/python3 \
		--build-dir $(@D)/build
endef

OPEN8030_VERSION_TEXT = $(if $(OPEN8030_OVERRIDE_SRCDIR),$(shell git -C $(OPEN8030_OVERRIDE_SRCDIR) describe --always --dirty 2>/dev/null),$(OPEN8030_VERSION))

# All loaders use the same basename. Preserve the published firmware paths
# for existing applications (Kestrel probes the old USB name directly).
ifeq ($(BR2_PACKAGE_OPEN8030_ROLE_AP),y)
define OPEN8030_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/$(OPEN8030_IMAGE) $(TARGET_DIR)$(OPEN8030_DEST)/$(OPEN8030_IMAGE)
	ln -sf $(OPEN8030_IMAGE) $(TARGET_DIR)$(OPEN8030_DEST)/open8030-ap.img
	echo "$(OPEN8030_VERSION_TEXT)" > $(TARGET_DIR)$(OPEN8030_DEST)/version
	$(if $(BR2_PACKAGE_OPEN8030_AIR_DEFAULT),touch,rm -f) $(TARGET_DIR)$(OPEN8030_DEST)/always
endef
else
define OPEN8030_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/$(OPEN8030_IMAGE) $(TARGET_DIR)$(OPEN8030_DEST)/$(OPEN8030_IMAGE)
	$(INSTALL) -D -m 0644 "$(OPEN8030_CONFIG_SOURCE)" $(TARGET_DIR)$(OPEN8030_DEST)/open8030.json
	ln -sf open8030.json $(TARGET_DIR)$(OPEN8030_DEST)/bb_config_gnd_open8030.json
	$(if $(BR2_PACKAGE_OPEN8030_TRANSPORT_USB),ln -sf $(OPEN8030_IMAGE),rm -f) $(TARGET_DIR)$(OPEN8030_DEST)/open8030-vrxpro-usb.img
	echo "$(OPEN8030_VERSION_TEXT)" > $(TARGET_DIR)$(OPEN8030_DEST)/open8030.version
endef
endif

$(eval $(generic-package))
