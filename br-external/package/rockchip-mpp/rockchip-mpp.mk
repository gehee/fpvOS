################################################################################
# rockchip-mpp  (Rockchip Media Process Platform)
################################################################################

# Pinned to the commit kestrel's decoder was written and validated against
# (referenced in kestrel vdec/vdec_rk.hpp). Upstream's develop branch moves;
# the hardware decode path is sensitive to MPP behaviour, so this stays pinned
# and is bumped deliberately, with a decode test on real hardware.
ROCKCHIP_MPP_VERSION = ed377c99a733e2cdbcc457a6aa3f0fcd438a9dff
ROCKCHIP_MPP_SITE = $(call github,rockchip-linux,mpp,$(ROCKCHIP_MPP_VERSION))
ROCKCHIP_MPP_LICENSE = Apache-2.0, MIT
ROCKCHIP_MPP_LICENSE_FILES = LICENSES/Apache-2.0 LICENSES/MIT

# kestrel includes <rockchip/rk_mpi.h> and links -lrockchip_mpp, so the headers
# and the shared library both have to reach the staging sysroot.
ROCKCHIP_MPP_INSTALL_STAGING = YES
ROCKCHIP_MPP_DEPENDENCIES = libdrm

# Upstream defaults build a static library and the test binaries; we want the
# shared library (the device's vendor build is librockchip_mpp.so.1) and none
# of the ~40 test programs.
ROCKCHIP_MPP_CONF_OPTS = \
	-DBUILD_TEST=OFF \
	-DENABLE_SHARED=ON \
	-DENABLE_STATIC=OFF

$(eval $(cmake-package))
