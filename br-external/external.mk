include $(sort $(wildcard $(BR2_EXTERNAL_FPVOS_PATH)/package/*/*.mk))

# Mesa for Panfrost, without LLVM. Buildroot's recipe enables LLVM (and, via
# the shader precompiler, OpenCL with Clang and libclc) whenever Panfrost is
# selected, but Panfrost's compiler is Mesa's own, and the OpenCL-C shaders are
# compiled on the build host by host-mesa3d (-Dmesa-clc=system). Built this
# way libgallium does not link libLLVM, so post-build.sh can drop the ~220 MB
# of LLVM, Clang, libclc and SPIR-V tools Buildroot installs into the target.
ifeq ($(BR2_PACKAGE_MESA3D_GALLIUM_DRIVER_PANFROST),y)
MESA3D_CONF_OPTS += -Dllvm=disabled
endif

# The kernel against its board's linux.hash (board/vrxpro for the goggle,
# board/ascent-lite for the air unit, common/ar9311 for Gnd485: the folder
# of the first kernel config fragment): its tarball, and its licence files for legal-info. Buildroot's own
# linux.hash only knows upstream's licence files, which Rockchip's tree does not
# match (legal-info fails), and Buildroot skips the tarball's check for any
# kernel but its own latest. A pin moved without a new hash fails the download.
ifeq ($(BR2_LINUX_KERNEL_CUSTOM_TARBALL),y)
LINUX_HASH_FILES = $(dir $(firstword $(call qstrip,$(BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES))))linux.hash
BR_NO_CHECK_HASH_FOR := $(filter-out $(LINUX_SOURCE),$(BR_NO_CHECK_HASH_FOR))
# Headers built from the same tarball (the air unit's Buildroot toolchain) are
# the same file, so they are checked against the same hash file.
ifeq ($(BR2_KERNEL_HEADERS_AS_KERNEL),y)
LINUX_HEADERS_HASH_FILES = $(LINUX_HASH_FILES)
endif
endif

# The Gnd485 partition parser also needs its layout when recovery is disabled
# for a RAM-only build. This is board policy, not a shared AR9311 flash map.
ifeq ($(BR2_FPVOS_BOARD_ASCENT_GND485),y)
define ASCENT_GND485_LAYOUT_KERNEL_HEADER
	$(INSTALL) -m 0644 $(BR2_EXTERNAL_FPVOS_PATH)/package/fpvos-update/backends/ascent-gnd485/layout.h $(LINUX_DIR)/drivers/mtd/parsers/fpvos_ar9311_layout.h
endef
LINUX_PRE_BUILD_HOOKS += ASCENT_GND485_LAYOUT_KERNEL_HEADER
endif

# The NAND kernel contains an independent recovery root, not the final rootfs
# (which includes match-built kernel modules and is packaged afterwards).
ifeq ($(BR2_PACKAGE_ASCENT_GND485_RECOVERY),y)
LINUX_DEPENDENCIES += ascent-gnd485-recovery
# linux.mk has already instantiated its generic package by this point.
$(LINUX_DIR)/.stamp_configured: $(ASCENT_GND485_RECOVERY_DIR)/.stamp_target_installed
define ASCENT_GND485_RECOVERY_KERNEL_CONFIG
	$(call KCONFIG_SET_OPT,CONFIG_INITRAMFS_SOURCE,"$(ASCENT_GND485_RECOVERY_DIR)/root $(ASCENT_GND485_RECOVERY_DIR)/nodes.list")
	$(call KCONFIG_SET_OPT,CONFIG_INITRAMFS_ROOT_UID,$(shell id -u))
	$(call KCONFIG_SET_OPT,CONFIG_INITRAMFS_ROOT_GID,$(shell id -g))
	$(call KCONFIG_ENABLE_OPT,CONFIG_INITRAMFS_COMPRESSION_GZIP)
endef
LINUX_KCONFIG_FIXUP_CMDS += $(ASCENT_GND485_RECOVERY_KERNEL_CONFIG)
endif
