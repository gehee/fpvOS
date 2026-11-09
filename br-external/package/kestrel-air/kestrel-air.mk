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
KESTREL_AIR_VERSION ?= b3fa662b25e03cd5d8a76544f0d941c34b5dd68d
KESTREL_AIR_LICENSE = GPL-3.0 with an additional permission
KESTREL_AIR_LICENSE_FILES = LICENSE LICENSE.exception
KESTREL_AIR_DEPENDENCIES = ar-libre
ifeq ($(BR2_PACKAGE_KESTREL_AIR_AR9311),y)
KESTREL_AIR_DEPENDENCIES += ar9311-camera-control ar9311-capture
KESTREL_AIR_BACKEND = ar9311

define KESTREL_AIR_BUILD_SUPERVISOR
	$(TARGET_CC) $(TARGET_CFLAGS) -Wall -Wextra -Werror $(TARGET_LDFLAGS) \
		$(KESTREL_AIR_PKGDIR)/../kestrel-common/supervise.c -o $(@D)/kestrel-air-supervise
endef
KESTREL_AIR_POST_BUILD_HOOKS += KESTREL_AIR_BUILD_SUPERVISOR
else
KESTREL_AIR_DEPENDENCIES += hi3516cv610-sdk
KESTREL_AIR_BACKEND = hisilicon
endif

# The toolchain and ar_libre's client library (ar-libre stages it with its
# headers); hi3516cv610-sdk puts the libraries kestrel-air runs with on the
# unit. KA_VERSION: what
# kestrel-air logs and shows, since the source here has no git history to
# describe.
KESTREL_AIR_MAKE_OPTS = \
	CROSS_COMPILE=$(TARGET_CROSS) \
	BACKEND=$(KESTREL_AIR_BACKEND) \
	LDFLAGS="$(TARGET_LDFLAGS)" \
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

ifeq ($(BR2_PACKAGE_KESTREL_AIR_AR9311),y)
define KESTREL_AIR_INSTALL_LAUNCHER
	$(INSTALL) -D -m 0755 $(KESTREL_AIR_PKGDIR)/ar9311-run $(TARGET_DIR)/usr/bin/kestrel-air-run
	$(INSTALL) -D -m 0755 $(@D)/kestrel-air-supervise $(TARGET_DIR)/usr/sbin/kestrel-air-supervise
	$(INSTALL) -D -m 0755 $(KESTREL_AIR_PKGDIR)/S60kestrel-air $(TARGET_DIR)/etc/init.d/S60kestrel-air
endef
KESTREL_AIR_POST_INSTALL_TARGET_HOOKS += KESTREL_AIR_INSTALL_LAUNCHER
endif

$(eval $(generic-package))
