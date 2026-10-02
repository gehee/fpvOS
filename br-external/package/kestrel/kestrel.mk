################################################################################
# kestrel  (fpvOS ground application)
################################################################################

# kestrel lives in its own repository. fpvOS pins it to an immutable name:
# a release TAG once there is a release, and a commit until then. Both
# repositories carry the same version number from the first release on.
#
# Model:
#   day to day   KESTREL_OVERRIDE_SRCDIR=/path/to/kestrel builds your working
#                tree and skips the download entirely
#   release      scripts/release.sh builds, and only once that succeeded tags
#                kestrel-gnd and writes the tag into KESTREL_PIN below, so an
#                fpvOS tag builds to the same thing forever, offline included
#
# Why never a branch name in KESTREL_PIN. Buildroot stores every download as
# a tarball named after <PKG>_VERSION and reuses it if present, so a branch
# would be fetched once and served from cache forever. That is the real
# reason Buildroot treats versions as immutable. The same goes for a moved
# tag - never move a release tag.
#
# Overrides, all from the environment:
#   KESTREL_VERSION=<tag|sha>  build one exact revision, ignoring the pin
#   KESTREL_BRANCH=<name>      build a branch's CURRENT head without a local
#                              checkout, e.g. main (bleeding edge). Resolved
#                              to a commit before Buildroot sees it, so the
#                              cache stays honest; needs network, hence
#                              opt-in only. Releases are tags, not a branch
#   KESTREL_SITE=<url>         a fork or a mirror
#   KESTREL_OVERRIDE_SRCDIR=   a local checkout; the download is skipped
KESTREL_SITE ?= https://github.com/gehee/kestrel-gnd.git
KESTREL_SITE_METHOD = git

# The pin. Written by scripts/release.sh at release time - a tag from then on.
KESTREL_PIN = bde0695f413e4717f70a41625fcc00ffbebdd013

# Precedence: an explicit KESTREL_VERSION, then a requested branch, then the pin.
ifeq ($(origin KESTREL_VERSION),undefined)
  ifdef KESTREL_BRANCH
    KESTREL_VERSION := $(shell git ls-remote -q "$(KESTREL_SITE)" "refs/heads/$(KESTREL_BRANCH)" 2>/dev/null | cut -f1)
    ifeq ($(strip $(KESTREL_VERSION)),)
      $(error kestrel: could not resolve branch '$(KESTREL_BRANCH)' at $(KESTREL_SITE) - offline, or no such branch)
    endif
  else
    KESTREL_VERSION := $(KESTREL_PIN)
  endif
endif

KESTREL_DEPENDENCIES = ffmpeg cairo libdrm freetype pixman libpng rockchip-mpp fpvos-vendor-libs

# The AR8030 baseband client library is proprietary and extracted from device
# firmware into vendor/. kestrel links it at runtime; the CMake build tolerates
# its absence (find_library warns) so CI builds without vendor blobs.
KESTREL_CONF_OPTS = -DUSE_RKMPP=ON
# The download is a tarball without .git, so tell the build which revision it
# is - the pin, a tag from the first release on - for its version stamp.
ifeq ($(KESTREL_OVERRIDE_SRCDIR),)
KESTREL_CONF_OPTS += -DKESTREL_GND_GIT_HASH_FALLBACK=$(KESTREL_VERSION)
endif
# The version the menu shows is the image's: fpvOS's VERSION, which
# scripts/release.sh writes before it builds a release.
KESTREL_CONF_OPTS += -DKESTREL_GND_VERSION_LABEL=$(shell cat $(BR2_EXTERNAL_FPVOS_PATH)/../VERSION)

$(eval $(cmake-package))
