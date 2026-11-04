#!/bin/sh
# fpvOS: the unit's USB network, in place of the stock usb_ip.sh. The stock
# config_ether.sh runs it once the USB gadget is switched to network (RNDIS),
# at boot (/factory/run_rndis_flag) or live (enable_rndis).
#
# 192.168.2.1: stock's 192.168.3.104 shares the goggle's subnet (USB 3.1, WiFi
# 4.1), so a PC with both plugged in routes it to the wrong interface. A DHCP
# server gives the PC an address on 192.168.2.0/24 (no gateway: the PC keeps its
# own routes), so no manual setup is needed on it.

ifconfig lo up
ifconfig usb0 down
ifconfig usb0 hw ether 00:23:11:06:90:04
ifconfig usb0 192.168.2.1 netmask 255.255.255.0 up
echo "air: usb0 is 192.168.2.1"

air=/usrdata/fpv/air
if [ -x $air/bin/udhcpd ]; then
	cat > /tmp/udhcpd.conf <<CONF
interface usb0
start 192.168.2.100
end 192.168.2.150
max_leases 51
lease_file /tmp/udhcpd.leases
option subnet 255.255.255.0
option lease 86400
CONF
	touch /tmp/udhcpd.leases
	# A second run (the gadget switched again) replaces the server. Found by
	# its config path: our udhcpd is built without pidfile support.
	for p in $(pidof udhcpd); do
		grep -q /tmp/udhcpd.conf /proc/$p/cmdline 2>/dev/null && kill $p && sleep 1
	done
	$air/bin/udhcpd /tmp/udhcpd.conf && echo "air: DHCP on usb0, 192.168.2.100-150"
fi
