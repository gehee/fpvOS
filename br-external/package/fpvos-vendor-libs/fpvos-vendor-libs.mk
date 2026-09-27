################################################################################
# fpvos-vendor-libs
#
# Installs the extracted vendor shared libraries into BOTH staging (so kestrel
# can link) and target (so it runs). Everything here comes from
# scripts/extract-vendor.py, i.e. from firmware the user owns - nothing is
# redistributed by fpvOS.
#
# Two reasons this exists rather than leaving it all to post-build.sh:
#
#  * kestrel links -lar8030_client for the AR8030 baseband API. Without the
#    library in staging the link fails with ~11 undefined bb_* symbols.
#
#  * rockchip-mali installs the Mali-G31 blob, but RK3568 is Mali-G52, and the
#    difference is not cosmetic: the G31 blob does not export
#    gbm_bo_get_modifier while the G52 one does, so linking against G31 fails.
#    Installing after rockchip-mali replaces libmali.so.1 with this board's
#    actual G52 library, which the libEGL/libGLESv2/libgbm symlinks then
#    resolve to.
################################################################################

FPVOS_VENDOR_LIBS_VERSION = 1.0
FPVOS_VENDOR_LIBS_SITE = $(BR2_EXTERNAL_FPVOS_PATH)/../vendor/rootfs/usr/lib
FPVOS_VENDOR_LIBS_SITE_METHOD = local
FPVOS_VENDOR_LIBS_INSTALL_STAGING = YES
# Must land after rockchip-mali so our G52 libmali wins.
FPVOS_VENDOR_LIBS_DEPENDENCIES = rockchip-mali

# Remove the destination first: these paths are symlinks created by
# rockchip-mali, and copying onto a symlink writes THROUGH it, silently
# overwriting whatever it points at instead of replacing the link.
# Libraries Buildroot builds from source. Their vendor copies stay in the blob
# set as a fallback but must not be installed over the built ones, or the
# from-source build is silently discarded and we ship the vendor binary while
# believing we ship ours.
#
#   librockchip_mpp - built by the rockchip-mpp package (Apache-2.0/MIT).
#                     Drop this exclusion to fall back to the vendor blob if a
#                     from-source MPP regresses hardware decode.
FPVOS_VENDOR_LIBS_SKIP = librockchip_mpp

define FPVOS_VENDOR_LIBS_INSTALL_CMDS
	for f in $(@D)/*.so*; do \
		[ -e "$$f" ] || continue; \
		b=$$(basename $$f); \
		case $$b in $(FPVOS_VENDOR_LIBS_SKIP)*) continue ;; esac; \
		rm -f $(1)/usr/lib/$$b; \
		$(INSTALL) -D -m 0755 $$f $(1)/usr/lib/$$b; \
	done; \
	for l in $(1)/usr/lib/*.so; do \
		[ -L "$$l" ] || continue; \
		case $$(readlink "$$l") in libmali-*) ln -sf libmali.so.1 "$$l" ;; esac; \
	done; \
	rm -f $(1)/usr/lib/libmali-bifrost-*
endef

define FPVOS_VENDOR_LIBS_INSTALL_STAGING_CMDS
	$(call FPVOS_VENDOR_LIBS_INSTALL_CMDS,$(STAGING_DIR))
endef

define FPVOS_VENDOR_LIBS_INSTALL_TARGET_CMDS
	$(call FPVOS_VENDOR_LIBS_INSTALL_CMDS,$(TARGET_DIR))
endef

$(eval $(generic-package))
