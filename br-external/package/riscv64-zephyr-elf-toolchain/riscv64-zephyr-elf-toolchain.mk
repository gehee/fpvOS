################################################################################
#
# riscv64-zephyr-elf-toolchain
#
################################################################################

# The Zephyr SDK's RISC-V cross compiler (GCC 14.3, prebuilt for x86_64 and
# aarch64 Linux), for open8030: the AR8030 runs an RV32 core. Only the compiler
# is used, not the rest of the SDK (its CMake package, host tools and QEMU).
RISCV64_ZEPHYR_ELF_TOOLCHAIN_VERSION = 1.0.1
RISCV64_ZEPHYR_ELF_TOOLCHAIN_SITE = https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v$(RISCV64_ZEPHYR_ELF_TOOLCHAIN_VERSION)
RISCV64_ZEPHYR_ELF_TOOLCHAIN_SOURCE = toolchain_gnu_linux-$(HOSTARCH)_riscv64-zephyr-elf.tar.xz
RISCV64_ZEPHYR_ELF_TOOLCHAIN_LICENSE = GPL-3.0+, LGPL-3.0+, GPL-3.0+ with GCC runtime exception (libgcc), BSD-3-Clause (picolibc)

HOST_RISCV64_ZEPHYR_ELF_TOOLCHAIN_INSTALL_DIR = $(HOST_DIR)/opt/riscv64-zephyr-elf

define HOST_RISCV64_ZEPHYR_ELF_TOOLCHAIN_INSTALL_CMDS
	rm -rf $(HOST_RISCV64_ZEPHYR_ELF_TOOLCHAIN_INSTALL_DIR)
	mkdir -p $(HOST_RISCV64_ZEPHYR_ELF_TOOLCHAIN_INSTALL_DIR)
	cp -rf $(@D)/* $(HOST_RISCV64_ZEPHYR_ELF_TOOLCHAIN_INSTALL_DIR)/
endef

$(eval $(host-generic-package))
