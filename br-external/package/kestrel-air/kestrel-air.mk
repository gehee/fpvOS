################################################################################
#
# kestrel-air  (fpvOS air-unit application)
#
################################################################################

# Pinned to a commit, never a branch (see ../kestrel/kestrel.mk for why).
# KESTREL_AIR_OVERRIDE_SRCDIR=/path/to/kestrel-air builds a local checkout instead,
# KESTREL_AIR_SITE another copy of the repository.
KESTREL_AIR_SITE ?= https://github.com/gehee/kestrel-air.git
KESTREL_AIR_SITE_METHOD = git
KESTREL_AIR_VERSION ?= 44c4d98b60436ddf6a46d667157508f0c804c5fd
KESTREL_AIR_LICENSE = GPL-3.0 with an additional permission
KESTREL_AIR_LICENSE_FILES = LICENSE LICENSE.exception
KESTREL_AIR_DEPENDENCIES = hi3516cv610-sdk ar-libre

# The toolchain and ar_libre's client library (ar-libre stages it with its
# headers); hi3516cv610-sdk puts the libraries kestrel-air runs with on the
# unit. KA_VERSION: what
# kestrel-air logs and shows, since the source here has no git history to
# describe.
KESTREL_AIR_MAKE_OPTS = \
	CROSS_COMPILE=$(TARGET_CROSS) \
	ARLIBRE=$(STAGING_DIR)/usr/share/ar-libre \
	KA_VERSION=$(KESTREL_AIR_VERSION_TEXT)

KESTREL_AIR_VERSION_TEXT = $(if $(KESTREL_AIR_OVERRIDE_SRCDIR),$(shell git -C $(KESTREL_AIR_OVERRIDE_SRCDIR) describe --always --dirty 2>/dev/null),$(shell echo $(KESTREL_AIR_VERSION) | cut -c1-8))

define KESTREL_AIR_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) $(KESTREL_AIR_MAKE_OPTS)
endef

define KESTREL_AIR_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/kestrel-air $(TARGET_DIR)/usrdata/fpv/air/kestrel-air
	echo "$(KESTREL_AIR_VERSION_TEXT)" > $(TARGET_DIR)/usrdata/fpv/air/kestrel-air.version
endef

$(eval $(generic-package))
