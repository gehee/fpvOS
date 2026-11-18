################################################################################
#
# ascent-lite-ffs  (FunctionFS and CDC-NCM as modules, for the Lite's stock kernel)
#
################################################################################

# The image keeps the stock kernel (see ascentlite_defconfig), which has no
# FunctionFS and no CDC-NCM; its USB gadget core and u_ether (built in for
# RNDIS) are, and export what f_fs.c and f_ncm.c need. So both are taken from
# the kernel tree the image builds its modules against and built out of tree:
# in the tree's config they would be built in or not at all (the configfs
# options that select them are bools).
ASCENT_LITE_FFS_VERSION = $(LINUX_VERSION)
ASCENT_LITE_FFS_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/ascent-lite-ffs/src
ASCENT_LITE_FFS_SITE_METHOD = local
ASCENT_LITE_FFS_LICENSE = GPL-2.0-or-later
ASCENT_LITE_FFS_DEPENDENCIES = linux

define ASCENT_LITE_FFS_COPY_SOURCE
	cp $(LINUX_DIR)/drivers/usb/gadget/function/f_fs.c \
		$(LINUX_DIR)/drivers/usb/gadget/function/u_fs.h \
		$(LINUX_DIR)/drivers/usb/gadget/function/f_ncm.c \
		$(LINUX_DIR)/drivers/usb/gadget/function/u_ncm.h $(@D)/
endef
ASCENT_LITE_FFS_PRE_BUILD_HOOKS += ASCENT_LITE_FFS_COPY_SOURCE

# Next to fpvOS_usb's hooks in the app volume, where its radio-stop loads
# usb_f_fs.ko and config_ether.sh loads usb_f_ncm.ko.
define ASCENT_LITE_FFS_INSTALL_APP
	$(INSTALL) -D -m 0644 $(@D)/usb_f_fs.ko $(TARGET_DIR)/usrdata/fpv/air/usb/usb_f_fs.ko
	$(INSTALL) -D -m 0644 $(@D)/usb_f_ncm.ko $(TARGET_DIR)/usrdata/fpv/air/usb/usb_f_ncm.ko
endef
ASCENT_LITE_FFS_POST_INSTALL_TARGET_HOOKS += ASCENT_LITE_FFS_INSTALL_APP

$(eval $(kernel-module))
$(eval $(generic-package))
