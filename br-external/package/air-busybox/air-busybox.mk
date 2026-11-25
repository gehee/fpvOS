################################################################################
#
# air-busybox  (a static udhcpd for the air unit's app volume)
#
################################################################################

# Buildroot's busybox source, built a second time: statically linked (the stock
# rootfs's libc is not ours) and with only the DHCP server, for the unit's USB
# network. Installed under the applet's name, which busybox dispatches on.
AIR_BUSYBOX_VERSION = $(BUSYBOX_VERSION)
AIR_BUSYBOX_SITE = $(BUSYBOX_SITE)
AIR_BUSYBOX_SOURCE = $(BUSYBOX_SOURCE)
AIR_BUSYBOX_DL_SUBDIR = busybox
AIR_BUSYBOX_LICENSE = GPL-2.0
AIR_BUSYBOX_LICENSE_FILES = LICENSE

AIR_BUSYBOX_APPDIR = /usrdata/fpv/air

# Nothing but the DHCP server, statically linked: allnoconfig, the three
# options switched on, oldconfig for what follows from them; and a check that
# they stuck.
define AIR_BUSYBOX_CONFIGURE_CMDS
	$(MAKE) -C $(@D) allnoconfig
	sed -i -e 's/^# CONFIG_STATIC is not set/CONFIG_STATIC=y/' \
		-e 's/^# CONFIG_LFS is not set/CONFIG_LFS=y/' \
		-e 's/^# CONFIG_UDHCPD is not set/CONFIG_UDHCPD=y/' $(@D)/.config
	yes '' | $(MAKE) -C $(@D) oldconfig
	grep -q '^CONFIG_UDHCPD=y' $(@D)/.config && grep -q '^CONFIG_STATIC=y' $(@D)/.config && \
		grep -q '^CONFIG_LFS=y' $(@D)/.config
endef

define AIR_BUSYBOX_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) CROSS_COMPILE="$(TARGET_CROSS)" \
		CC="$(TARGET_CC)" busybox
endef

define AIR_BUSYBOX_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/busybox $(TARGET_DIR)$(AIR_BUSYBOX_APPDIR)/bin/udhcpd
endef

$(eval $(generic-package))

# Busybox's own hash file checks the shared tarball (and LICENSE for
# legal-info). After generic-package, which sets AIR_BUSYBOX_HASH_FILES to
# this package's (missing) air-busybox.hash and would override it if set above.
AIR_BUSYBOX_HASH_FILES = $(BUSYBOX_PKGDIR)/busybox.hash
