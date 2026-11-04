# ---- fpvOS hook (added at build time by fpvOS) -------------------------
# Everything above is stock: board detect, the USB ACM gadget and the PC
# tool's updater, the MPP modules. From here the radio and the air app are
# fpvOS's if air/start.sh is present and air/disable is not, and stock
# otherwise: below this block is the stock radio driver and air app, untouched.
# `touch /usrdata/fpv/air/disable` gives the stock radio and app from the next
# boot. `touch /usrdata/fpv/air/stock-once` does the same for the next boot only:
# the file is deleted here, so the boot after that is fpvOS again (for comparing).
echo "fpvOS: $(cat /usrdata/fpv/air/VERSION 2>/dev/null || echo no air app)"
if [ -e /usrdata/fpv/air/stock-once ]; then
	rm -f /usrdata/fpv/air/stock-once
	sync
	echo "fpvOS: stock radio and air app for this boot only"
elif [ -x /usrdata/fpv/air/start.sh ] && [ ! -e /usrdata/fpv/air/disable ]; then
	/usrdata/fpv/air/start.sh $board_type $board_ver $HW_VER $rf_board > /tmp/air.log 2>&1 &
	exit 0
fi

