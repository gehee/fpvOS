################################################################################
#
# air-dropbear  (an SSH server in the air unit's app volume)
#
################################################################################

# Buildroot's own dropbear source, built again for the app volume: the air
# unit's rootfs stays stock, so the server lives in /usrdata/fpv/air/bin.
# - statically linked: the stock rootfs has an older musl, without crypt()
# - password login compiled in: root/root by default, the hash written at build
#   time (FPVOS_AIR_ROOT_PASSWORD, empty for none, in board/ascent-lite/
#   post-image.sh) and mounted over the stock /etc/shadow by air/start.sh, which
#   runs dropbear with -s -g when there is no password; public keys from
#   FPVOS_AIR_SSH_KEYS as well
AIR_DROPBEAR_VERSION = $(DROPBEAR_VERSION)
AIR_DROPBEAR_SITE = $(DROPBEAR_SITE)
AIR_DROPBEAR_SOURCE = $(DROPBEAR_SOURCE)
AIR_DROPBEAR_DL_SUBDIR = dropbear
AIR_DROPBEAR_LICENSE = MIT, BSD-2-Clause, Public domain
AIR_DROPBEAR_LICENSE_FILES = LICENSE

AIR_DROPBEAR_CONF_OPTS = \
	--enable-static \
	--disable-zlib \
	--disable-pam \
	--disable-lastlog \
	--disable-utmp \
	--disable-utmpx \
	--disable-wtmp \
	--disable-wtmpx \
	--disable-loginfunc \
	--disable-pututline \
	--disable-pututxline

AIR_DROPBEAR_APPDIR = /usrdata/fpv/air
AIR_DROPBEAR_PROGRAMS = dropbear dropbearkey scp

define AIR_DROPBEAR_LOCALOPTIONS
	echo '#define DROPBEAR_SVR_PASSWORD_AUTH 1'     >> $(@D)/localoptions.h
	echo '#define DROPBEAR_SVR_PAM_AUTH 0'          >> $(@D)/localoptions.h
	echo '#define DEFAULT_PATH "$(AIR_DROPBEAR_APPDIR)/bin:/usr/bin:/bin"' >> $(@D)/localoptions.h
	echo '#define DEFAULT_ROOT_PATH "$(AIR_DROPBEAR_APPDIR)/bin:/usr/sbin:/usr/bin:/sbin:/bin"' >> $(@D)/localoptions.h
endef
AIR_DROPBEAR_POST_EXTRACT_HOOKS += AIR_DROPBEAR_LOCALOPTIONS

AIR_DROPBEAR_MAKE = \
	$(MAKE) MULTI=1 SCPPROGRESS=0 PROGRAMS="$(AIR_DROPBEAR_PROGRAMS)"

define AIR_DROPBEAR_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/dropbearmulti \
		$(TARGET_DIR)$(AIR_DROPBEAR_APPDIR)/bin/dropbearmulti
	$(foreach p,$(AIR_DROPBEAR_PROGRAMS),
		ln -sf dropbearmulti $(TARGET_DIR)$(AIR_DROPBEAR_APPDIR)/bin/$(p)
	)
endef

$(eval $(autotools-package))
