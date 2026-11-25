#!/usr/bin/env python3
"""S44ar9311-radio: a chip whose firmware did not start is reset (SDIO host and
power sequencer rebound) and loaded once more. Run against stand-ins for sysfs,
/dev/arlink0, modprobe and rmmod."""
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1]/'src/S44ar9311-radio'


class RadioStart(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = root = Path(tmp.name)
        for d in ('bin', 'dev', 'proc', 'lib/firmware', 'sys/module',
                  'sys/bus/platform/drivers/dwmmc_artosyn', 'sys/bus/platform/drivers/ar9311-radio-pwrseq',
                  'sys/devices/radio-pwrseq/driver'):
            (root/d).mkdir(parents=True)
        (root/'sys/bus/platform/drivers/ar9311-radio-pwrseq/radio-pwrseq').symlink_to(root/'sys/devices/radio-pwrseq')
        (root/'sys/bus/platform/drivers/dwmmc_artosyn/1b00000.mmc').mkdir()
        for f in ('open8030.img', 'open8030.json'): (root/'lib/firmware'/f).write_text('x')
        (root/'proc/modules').write_text('')
        text = SCRIPT.read_text()
        text = text.replace('[ -c /dev/arlink0 ]', f'[ -e {root}/dev/arlink0 ]')
        for p in ('/etc/default/ar9311-radio', '/sys/', '/proc/modules', '/dev/kmsg', '/lib/firmware/'):
            text = text.replace(p, f'{root}{p}')
        text = '#!/bin/sh\nPATH=%s/bin:$PATH\n' % root + text.split('\n', 1)[1]
        self.script = root/'S44'; self.script.write_text(text)
        # The chip comes up on the Nth arlink load (0: never); sysfs writes are logged.
        self.command('modprobe', f'''echo "modprobe $*" >> {root}/calls
case "$1" in arlink)
  n=$(cat {root}/loads 2>/dev/null || echo 0); n=$((n + 1)); echo $n > {root}/loads
  mkdir -p {root}/sys/module/arlink; echo "arlink 1 0" > {root}/proc/modules
  [ "$(cat {root}/up-on)" != "$n" ] || : > {root}/dev/arlink0 ;;
esac''')
        self.command('rmmod', f'echo "rmmod $*" >> {root}/calls; rm -rf {root}/sys/module/arlink; : > {root}/proc/modules')
        for name in ('sleep', 'dmesg'): self.command(name, ':')
        for drv in ('dwmmc_artosyn', 'ar9311-radio-pwrseq'):
            for op in ('bind', 'unbind'):
                p = root/'sys/bus/platform/drivers'/drv/op
                p.write_text('')

    def command(self, name, body):
        p = self.root/'bin'/name; p.write_text(f'#!/bin/sh\n{body}\n'); p.chmod(0o755)

    def start(self, up_on):
        (self.root/'up-on').write_text(str(up_on))
        return subprocess.run(['sh', str(self.script), 'start'], capture_output=True, text=True, timeout=20)

    def calls(self):
        p = self.root/'calls'
        return p.read_text() if p.exists() else ''

    def sysfs(self, drv, op):
        return (self.root/'sys/bus/platform/drivers'/drv/op).read_text()

    def test_a_chip_that_starts_is_not_reset(self):
        r = self.start(1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn('rmmod', self.calls())
        self.assertEqual(self.sysfs('ar9311-radio-pwrseq', 'bind'), '')

    def test_a_chip_that_did_not_start_is_reset_and_loaded_again(self):
        r = self.start(2)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('after a chip reset', r.stdout)
        self.assertIn('rmmod arlink', self.calls())
        self.assertEqual(self.calls().count('modprobe arlink'), 2)
        # Host unbound first, then the sequencer rebound, then the host bound.
        self.assertEqual(self.sysfs('dwmmc_artosyn', 'unbind'), '1b00000.mmc\n')
        self.assertEqual(self.sysfs('ar9311-radio-pwrseq', 'unbind'), 'radio-pwrseq\n')
        self.assertEqual(self.sysfs('ar9311-radio-pwrseq', 'bind'), 'radio-pwrseq\n')
        self.assertEqual(self.sysfs('dwmmc_artosyn', 'bind'), '1b00000.mmc\n')

    def test_only_one_reset(self):
        r = self.start(0)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('failed after a chip reset', r.stderr)
        self.assertEqual(self.calls().count('modprobe arlink'), 2)

    def test_a_later_start_with_the_driver_loaded_resets_too(self):
        self.start(0)
        (self.root/'loads').write_text('0')
        r = self.start(1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('after a chip reset', r.stdout)


if __name__ == '__main__':
    unittest.main()
