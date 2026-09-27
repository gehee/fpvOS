################################################################################
# btop  (terminal resource monitor)
################################################################################

BTOP_VERSION = 1.4.7
BTOP_SITE = $(call github,aristocratos,btop,v$(BTOP_VERSION))
BTOP_LICENSE = Apache-2.0
BTOP_LICENSE_FILES = LICENSE

# btop's CMakeLists refuses in-source builds.
BTOP_SUPPORTS_IN_SOURCE_BUILD = NO

# No GPU panel: the Mali has no NVML/ROCm/Intel backend for it to read, so the
# probe would only add startup time. LTO off - it buys nothing measurable here
# and needs the cross gcc-ar/gcc-ranlib wrappers wired through CMake.
#
# Buildroot's toolchain file names the platform "Buildroot", not "Linux", so
# CMake never sets LINUX and btop stops with "is not supported". Say it.
BTOP_CONF_OPTS = \
	-DLINUX=ON \
	-DBTOP_GPU=OFF \
	-DBTOP_LTO=OFF \
	-DBTOP_STATIC=OFF

# CMake stamps `git rev-parse HEAD` of the source dir into the version string;
# built from a tarball inside our tree that is Buildroot's commit, which would
# read as btop's. No git, no suffix: plain "1.4.7".
BTOP_CONF_ENV = GIT_DIR=/nonexistent

$(eval $(cmake-package))
