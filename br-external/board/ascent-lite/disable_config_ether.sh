#!/bin/sh
# fpvOS: undoes config_ether.sh, in place of the stock disable_config_ether.sh,
# whichever function it set up (NCM, or stock's RNDIS).

cd /sys/kernel/config/usb_gadget/ether || exit 0
echo > UDC
for fn in ncm.usb0 rndis.usb0; do
	[ -e configs/c.1/$fn ] && rm configs/c.1/$fn
	[ -d functions/$fn ] && rmdir functions/$fn
done
rmdir configs/c.1/strings/0x409
rm -f os_desc/c.1
rmdir configs/c.1
rmdir strings/0x409
cd ..
rmdir ether
cd /root/
umount /sys/kernel/config/
