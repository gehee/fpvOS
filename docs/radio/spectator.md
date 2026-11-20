# Building spectator support

Receive-only spectator mode is implemented by Open8030 and Kestrel ground;
it needs no new kernel driver or updater format. Automatic recovery for late
joiners additionally needs Kestrel Air with periodic spectator recovery enabled. Native Ascent VRX and P1
goggle runtimes use the normal receiver settings storage for the mode and
manual tuning. Existing profiles default to Pilot.

Build a matching Open8030 source containing the LST2 capability API (revision 2) and a
Kestrel native runtime containing the spectator RADIO menu. For local work,
use Buildroot's `OPEN8030_OVERRIDE_SRCDIR` and the normal
`KESTREL_NATIVE_IMAGE` runtime input. Keep overrides outside tracked board
profiles. Release builds must pin the corresponding published Open8030 revision
and package the matching Kestrel runtime; an old pinned radio firmware does
not acquire the feature from a newer UI alone.

No board-specific spectator startup script is required. Kestrel owns the radio
session, reads video directly, and switches modes through its normal settings
and command model. See Kestrel's `docs/spectator.md` and Open8030's
`docs/spectator.md` for setup, protocol and receive-only following behavior and limitations.

For late-join recovery, build matching Kestrel Air source through the normal
package/local source override. Recovery defaults on in new air configurations. The pilot shows read-only
frequency, bandwidth and stream ID. Existing saved air overrides are respected.
Manual initial RF tuning is still required. Subsequent announced channel and
bandwidth changes are followed by LST2-capable radio firmware. Video-carried announcements are not a
common-channel RF discovery beacon, and automatic RF acquisition is not yet
implemented.
