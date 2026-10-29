################################################################################
#
# open8030
#
################################################################################

# Open8030, the open-source firmware for the AR8030 radio chip (gehee/Open8030,
# a fork of mh1412/Open8030), built from source and installed next to stock's:
#   goggle    /lib/firmware/open8030-vrxpro-usb.img and its radio config
#             bb_config_gnd_open8030.json; bb_only.sh loads them unless
#             kestrel-gnd.yaml says ar8030_firmware: 0
#   air unit  /usrdata/fpv/air/open8030/open8030-ap.img, the AP role, with
#             the board's stock radio config; start.sh loads it on a Lite
#             or Lite+ when /usrdata/fpv/air/open8030/always exists (one
#             image for both: the Lite's profile builds the same bytes)
# Both ends are pinned to Open8030's main (the AP role, the automatic link
# width and the host requests, run on the goggle and the air unit since
# 2026-10-19), each built with its own flags. OPEN8030_OVERRIDE_SRCDIR builds a
# local checkout instead, OPEN8030_SITE another copy of the repository.
#
# The board profiles (register defaults, pins and frame-control-header keys,
# reverse engineered from the stock radio firmware) and the goggle's radio
# config come from the open8030-profiles package, a published archive - or
# from OPEN8030_PRIVATE_DIR when it is set, a local copy (vendor/open8030,
# which scripts/open8030-private.sh fills from an Open8030 checkout).
ifeq ($(BR2_PACKAGE_AR9311_RADIO),y)
OPEN8030_PRIVATE_DIR ?= $(BR2_EXTERNAL_FPVOS_PATH)/../vendor/open8030
OPEN8030_CONFIG_DIR = $(OPEN8030_PROFILES_DIR)
OPEN8030_DEPENDENCIES += open8030-profiles
endif

ifeq ($(OPEN8030_PRIVATE_DIR),)
OPEN8030_PRIVATE_DIR = $(OPEN8030_PROFILES_DIR)
OPEN8030_DEPENDENCIES += open8030-profiles
endif

ifeq ($(BR2_PACKAGE_KESTREL_AIR),y)
OPEN8030_PIN = 89d3c634c11d5665dcc17401c5d8b3172bbacf8b
OPEN8030_PROFILE = ascent-lite-plus.c
OPEN8030_CFLAGS = -DAR_ROLE_AP -DAR_FACTORY_OPTIONAL
OPEN8030_IMAGE = open8030-ap.img
OPEN8030_DEST = /usrdata/fpv/air/open8030
else ifeq ($(BR2_PACKAGE_AR9311_RADIO),y)
OPEN8030_PIN = 89d3c634c11d5665dcc17401c5d8b3172bbacf8b
OPEN8030_PROFILE = ascent-vrx.c
OPEN8030_CFLAGS =
OPEN8030_IMAGE = open8030-gnd485-sdio.img
OPEN8030_DEST = /lib/firmware
OPEN8030_SITE ?= https://github.com/mh1412/Open8030.git
else
OPEN8030_PIN = 89d3c634c11d5665dcc17401c5d8b3172bbacf8b
OPEN8030_PROFILE = ascent-vrx-pro.c
OPEN8030_CFLAGS = -DAR_FORCE_USB
OPEN8030_IMAGE = open8030-vrxpro-usb.img
OPEN8030_DEST = /lib/firmware
endif

OPEN8030_CONFIG ?= bb_config_gnd_open8030.json
OPEN8030_CONFIG_DIR ?= $(OPEN8030_PRIVATE_DIR)

OPEN8030_VERSION ?= $(OPEN8030_PIN)
OPEN8030_SITE ?= https://github.com/gehee/Open8030.git
OPEN8030_SITE_METHOD = git
# Zephyr's kernel and the compiler's runtime are compiled into the image.
OPEN8030_LICENSE = MIT, Apache-2.0 (Zephyr), GPL-3.0+ with GCC runtime exception (libgcc)
OPEN8030_LICENSE_FILES = LICENSE THIRD_PARTY.md
# Firmware for the radio chip: the target's toolchain is not used.
OPEN8030_ADD_TOOLCHAIN_DEPENDENCY = NO
OPEN8030_DEPENDENCIES += \
	host-riscv64-zephyr-elf-toolchain host-zephyr host-zephyr-python \
	host-ninja $(BR2_CMAKE_HOST_DEPENDENCY)

# The --cflags= form: a value starting with -D would read as an option.
define OPEN8030_BUILD_CMDS
	test -r $(OPEN8030_PRIVATE_DIR)/$(OPEN8030_PROFILE) || \
		{ echo "Missing Open8030 board profile: see docs/BUILD.md and OPEN8030_PRIVATE_DIR" >&2; exit 1; }
	cd $(@D) && $(HOST_MAKE_ENV) USER_CACHE_DIR=$(@D)/build/cache \
		$(HOST_DIR)/bin/python3 ./open8030 image \
		--profile $(OPEN8030_PRIVATE_DIR)/$(OPEN8030_PROFILE) \
		--output $(@D)/$(OPEN8030_IMAGE) \
		--cflags="$(OPEN8030_CFLAGS)" \
		--zephyr $(HOST_ZEPHYR_WORKSPACE)/zephyr \
		--toolchain $(HOST_RISCV64_ZEPHYR_ELF_TOOLCHAIN_INSTALL_DIR) \
		--python $(HOST_DIR)/bin/python3 \
		--build-dir $(@D)/build
endef

OPEN8030_VERSION_TEXT = $(if $(OPEN8030_OVERRIDE_SRCDIR),$(shell git -C $(OPEN8030_OVERRIDE_SRCDIR) describe --always --dirty 2>/dev/null),$(OPEN8030_VERSION))

ifeq ($(BR2_PACKAGE_KESTREL_AIR),y)
define OPEN8030_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/$(OPEN8030_IMAGE) $(TARGET_DIR)$(OPEN8030_DEST)/$(OPEN8030_IMAGE)
	echo "$(OPEN8030_VERSION_TEXT)" > $(TARGET_DIR)$(OPEN8030_DEST)/version
	$(if $(BR2_PACKAGE_OPEN8030_AIR_DEFAULT),touch,rm -f) $(TARGET_DIR)$(OPEN8030_DEST)/always
endef
else
define OPEN8030_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/$(OPEN8030_IMAGE) $(TARGET_DIR)$(OPEN8030_DEST)/$(OPEN8030_IMAGE)
	$(INSTALL) -D -m 0644 $(OPEN8030_CONFIG_DIR)/$(OPEN8030_CONFIG) \
		$(TARGET_DIR)$(OPEN8030_DEST)/$(OPEN8030_CONFIG)
	echo "$(OPEN8030_VERSION_TEXT)" > $(TARGET_DIR)$(OPEN8030_DEST)/open8030.version
endef
endif

$(eval $(generic-package))
