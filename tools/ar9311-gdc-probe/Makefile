ifeq ($(KERNELRELEASE),)
CROSS_COMPILE ?= aarch64-linux-
ARCH ?= arm64

.PHONY: all module clean
all: module gdc-test gdc-rgba gdc-invalid

module:
	@test -n "$(KDIR)" || { echo 'Set KDIR to the configured, built target kernel'; exit 1; }
	$(MAKE) -C "$(KDIR)" M="$(CURDIR)" ARCH=$(ARCH) CROSS_COMPILE="$(CROSS_COMPILE)" modules

gdc-test: test.c probe_abi.h
	$(CROSS_COMPILE)gcc -O2 -Wall -Wextra -Werror test.c -lm -o $@

gdc-rgba: rgba.c probe_abi.h
	$(CROSS_COMPILE)gcc -O3 -Wall -Wextra -Werror rgba.c -lm -o $@

gdc-invalid: invalid.c probe_abi.h
	$(CROSS_COMPILE)gcc -O2 -Wall -Wextra -Werror invalid.c -o $@

clean:
	$(MAKE) -C "$(KDIR)" M="$(CURDIR)" ARCH=$(ARCH) CROSS_COMPILE="$(CROSS_COMPILE)" clean
	rm -f gdc-test gdc-rgba gdc-invalid
else
obj-m := gdc_probe.o
endif
