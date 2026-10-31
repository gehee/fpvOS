################################################################################
#
# ar-libre  (open AR8030 host stack: arlink.ko + libar8030_client.so)
#
################################################################################

# fpvOS's own host stack for the AR8030, in place of Artosyn's kernel driver,
# daemon and client library:
#   arlink.ko            uploads the baseband firmware at power-on, then is
#                        /dev/arlink0, a frame pipe to the running chip
#   libar8030_client.so  the client API kestrel-gnd and kestrel-air call, in-process
# Pinned to a commit (never a branch); AR_LIBRE_OVERRIDE_SRCDIR builds a local
# checkout instead, AR_LIBRE_SITE another copy of the repository.
#
# The goggle and the air unit run the same commit: the SDIO reader thread that
# fixed the air-side link drops and the goggle's radio recovery are both in it.
AR_LIBRE_SITE ?= https://github.com/gehee/ar_libre.git
AR_LIBRE_SITE_METHOD = git
AR_LIBRE_VERSION ?= 5c66a0f7363e5a576a8f9fce3667805b7e39d426
AR_LIBRE_LICENSE = GPL-2.0-or-later
AR_LIBRE_LICENSE_FILES = LICENSE
AR_LIBRE_INSTALL_STAGING = YES

# arlink.ko is built against the image's own kernel build (on the air unit,
# kernel.org's 5.10.221 with the stock modules' vermagic; see ascentlite_defconfig).
AR_LIBRE_MODULE_SUBDIRS = driver

ifeq ($(BR2_PACKAGE_KESTREL_AIR),y)

# The library, for kestrel-air to link against. The directory layout in staging
# is what kestrel-air's Makefile calls ARLIBRE: <dir>/lib has the library and
# its headers.
define AR_LIBRE_BUILD_LIB
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D)/lib CROSS_COMPILE=$(TARGET_CROSS)
endef
AR_LIBRE_POST_BUILD_HOOKS += AR_LIBRE_BUILD_LIB

define AR_LIBRE_INSTALL_STAGING_CMDS
	$(INSTALL) -d $(STAGING_DIR)/usr/share/ar-libre/lib
	$(INSTALL) -m 0644 $(@D)/lib/arlink.h $(@D)/lib/ioctl_sizes.inc \
		$(STAGING_DIR)/usr/share/ar-libre/lib/
	$(INSTALL) -m 0755 $(@D)/lib/libar8030_client.so \
		$(STAGING_DIR)/usr/share/ar-libre/lib/
endef

# On the unit they go next to kestrel-air, in the app volume.
define AR_LIBRE_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/lib/libar8030_client.so \
		$(TARGET_DIR)/usrdata/fpv/air/lib/libar8030_client.so
	$(INSTALL) -D -m 0644 $(@D)/driver/arlink.ko \
		$(TARGET_DIR)/usrdata/fpv/air/arlink.ko
	echo "$(if $(AR_LIBRE_OVERRIDE_SRCDIR),$(shell git -C $(AR_LIBRE_OVERRIDE_SRCDIR) describe --always --dirty 2>/dev/null),$(AR_LIBRE_VERSION))" \
		> $(TARGET_DIR)/usrdata/fpv/air/ar-libre.version
endef

else

ifeq ($(BR2_STATIC_LIBS),y)
define AR_LIBRE_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -pthread -c $(@D)/lib/arlink.c -o $(@D)/lib/arlink.o
	$(TARGET_AR) rcs $(@D)/lib/libar8030_client.a $(@D)/lib/arlink.o
endef

define AR_LIBRE_INSTALL_STAGING_CMDS
	$(INSTALL) -D -m 0644 $(@D)/lib/libar8030_client.a $(STAGING_DIR)/usr/lib/libar8030_client.a
	$(INSTALL) -D -m 0644 $(@D)/lib/arlink.h $(STAGING_DIR)/usr/include/arlink.h
endef
else

# CFLAGS through the environment: the Makefile adds -fPIC and friends to it.
define AR_LIBRE_BUILD_CMDS
	CFLAGS="$(TARGET_CFLAGS)" $(TARGET_MAKE_ENV) $(MAKE) -C $(@D)/lib CC="$(TARGET_CC)"
endef

define AR_LIBRE_INSTALL_STAGING_CMDS
	$(INSTALL) -D -m 0755 $(@D)/lib/libar8030_client.so $(STAGING_DIR)/usr/lib/libar8030_client.so
	$(INSTALL) -D -m 0644 $(@D)/lib/arlink.h $(STAGING_DIR)/usr/include/arlink.h
endef

define AR_LIBRE_INSTALL_TARGET_CMDS
	rm -f $(TARGET_DIR)/usr/lib/libar8030_client.so
	$(INSTALL) -D -m 0755 $(@D)/lib/libar8030_client.so $(TARGET_DIR)/usr/lib/libar8030_client.so
endef

endif

endif

$(eval $(kernel-module))
$(eval $(generic-package))
