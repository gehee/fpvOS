################################################################################
#
# open8030-profiles  (what Open8030's radio firmware is built with)
#
################################################################################
# Open8030's board profiles for the Ascent Lite/Lite+ (ascent-lite-plus.c, one
# image for both) and the VRX Pro (ascent-vrx-pro.c), the register defaults
# they include (bb_defaults.inc) and the goggle radio's configuration under
# Open8030 (bb_config_gnd_open8030.json), in one archive with its SHA256SUMS.
# Register defaults, pin records, frame-control-header keys and flash parts,
# reverse engineered from Caddx's stock radio firmware (Ascent 18.21.10).
# The open8030 package builds with them from here, unless OPEN8030_PRIVATE_DIR
# names a local copy.
OPEN8030_PROFILES_VERSION = 20261022
OPEN8030_PROFILES_SOURCE = open8030-profiles-$(OPEN8030_PROFILES_VERSION).tar.gz
OPEN8030_PROFILES_SITE = https://gist.githubusercontent.com/gehee/96924eccf93961f646ea68832a04aa5c/raw/03329b4f3b4fc82ca5d77dc5b4c95cb6cfa0e376
OPEN8030_PROFILES_LICENSE = reverse engineered from the Caddx stock radio firmware
OPEN8030_PROFILES_LICENSE_FILES = README
OPEN8030_PROFILES_INSTALL_TARGET = NO

# Each file checked against the archive's own SHA256SUMS (the archive itself
# is checked by the .hash file).
define OPEN8030_PROFILES_CHECK
	cd $(@D) && sha256sum -c --quiet SHA256SUMS
endef
OPEN8030_PROFILES_POST_EXTRACT_HOOKS += OPEN8030_PROFILES_CHECK

# Where the open8030 package finds them.
OPEN8030_PROFILES_DIR = $(BUILD_DIR)/open8030-profiles-$(OPEN8030_PROFILES_VERSION)

$(eval $(generic-package))
