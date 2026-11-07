################################################################################
#
# ascent-lite-ffs  (FunctionFS as a module, for the Lite's stock kernel)
#
################################################################################

# The image keeps the stock kernel (see ascentlite_defconfig), which has no
# FunctionFS; its USB gadget core is built in and exports what f_fs.c needs.
# So f_fs.c is taken from the kernel tree the image builds its modules against
# and built out of tree: in the tree's config it would be built in or not at all
# (the configfs option that selects it is a bool).
ASCENT_LITE_FFS_VERSION = $(LINUX_VERSION)
ASCENT_LITE_FFS_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/package/ascent-lite-ffs/src
ASCENT_LITE_FFS_SITE_METHOD = local
ASCENT_LITE_FFS_LICENSE = GPL-2.0-or-later
ASCENT_LITE_FFS_DEPENDENCIES = linux

define ASCENT_LITE_FFS_COPY_SOURCE
	cp $(LINUX_DIR)/drivers/usb/gadget/function/f_fs.c \
		$(LINUX_DIR)/drivers/usb/gadget/function/u_fs.h $(@D)/
endef
ASCENT_LITE_FFS_PRE_BUILD_HOOKS += ASCENT_LITE_FFS_COPY_SOURCE

# Next to fpvOS_usb's hooks in the app volume, where its radio-stop loads it.
define ASCENT_LITE_FFS_INSTALL_APP
	$(INSTALL) -D -m 0644 $(@D)/usb_f_fs.ko $(TARGET_DIR)/usrdata/fpv/air/usb/usb_f_fs.ko
endef
ASCENT_LITE_FFS_POST_INSTALL_TARGET_HOOKS += ASCENT_LITE_FFS_INSTALL_APP

$(eval $(kernel-module))
$(eval $(generic-package))
