#!/usr/bin/env python3
"""fpvos-wifi keeps the access point's clients off SSH and the USB link."""
from pathlib import Path
import ipaddress
import os
import re
import subprocess
import tempfile
import unittest

BOARD = Path(__file__).resolve().parents[1]
WIFI = BOARD / 'rootfs-overlay/usr/sbin/fpvos-wifi'

# A stand-in iptables: -C answers from the rules inserted so far, -I records
# one (or fails, with FAIL_INSERT set); every call is logged.
FAKE = r'''#!/bin/sh
echo "$*" >> "$LOG"
op=$1; shift
case $op in
    -C) grep -qxF -- "$*" "$RULES" 2>/dev/null ;;
    -I) [ -z "$FAIL_INSERT" ] || exit 1; echo "$*" >> "$RULES" ;;
    *) exit 2 ;;
esac
'''


class Guard(unittest.TestCase):
    def setUp(self):
        self.text = WIFI.read_text()
        rules = re.search(r"^GUARD_RULES='.*?'\n", self.text, re.S | re.M).group(0)
        guard = re.search(r'^guard\(\) \{\n.*?^\}\n', self.text, re.S | re.M).group(0)
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.d = Path(temp.name)
        (self.d / 'bin').mkdir()
        (self.d / 'guard.sh').write_text(rules + guard + 'guard\n')

    def run_guard(self, iptables=True, **env):
        fake = self.d / 'bin/iptables'
        if iptables:
            fake.write_text(FAKE); fake.chmod(0o755)
        else:
            fake.unlink(missing_ok=True)
        e = dict(os.environ, PATH=f'{self.d}/bin:/usr/bin:/bin', LOG=str(self.d / 'log'), RULES=str(self.d / 'rules'), **env)
        return subprocess.run(['sh', str(self.d / 'guard.sh')], env=e).returncode

    def rules(self):
        path = self.d / 'rules'
        return path.read_text().splitlines() if path.exists() else []

    def test_drops_ssh_and_the_usb_link_from_wlan0(self):
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.rules(), ['INPUT -i wlan0 -d 192.168.3.0/24 -j DROP',
                                        'INPUT -i wlan0 -p tcp --dport 22 -j DROP'])

    def test_a_second_start_adds_nothing(self):
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(self.run_guard(), 0)
        self.assertEqual(len(self.rules()), 2)

    def test_failure_is_reported(self):
        self.assertNotEqual(self.run_guard(FAIL_INSERT='1'), 0)
        self.assertNotEqual(self.run_guard(iptables=False), 0)

    def test_the_rules_cover_the_address_dropbear_listens_on(self):
        args = re.search(r'^DROPBEAR_ARGS="-p ([0-9.]+):22"$',
                         (BOARD / 'rootfs-overlay/etc/default/dropbear').read_text(), re.M).group(1)
        usb = re.search(r'-d ([0-9./]+) -j DROP', self.text).group(1)
        self.assertIn(ipaddress.ip_address(args), ipaddress.ip_network(usb))
        self.assertIn('192.168.3.1', (BOARD / 'rootfs-overlay/etc/init.d/S30usbgadget').read_text())


class Start(unittest.TestCase):
    def test_guard_comes_before_the_ap_and_stops_it_on_failure(self):
        start = re.search(r'^start\(\) \{\n.*?^\}\n', WIFI.read_text(), re.S | re.M).group(0)
        guard = start.index('guard ||')
        self.assertLess(guard, start.index('ifconfig wlan0 $ADDR'))
        self.assertLess(guard, start.index('hostapd -B'))
        self.assertIn('stop; return 1', start[guard:start.index('\n', guard)])


def function(text, name):
    """A function of the script: a one-liner, or up to its closing brace."""
    n = re.escape(name)
    return re.search(rf'^{n}\(\) \{{ [^\n]*\}}\n|^{n}\(\) \{{\n.*?^\}}\n', text, re.S | re.M).group(0)


class Identity(unittest.TestCase):
    """/etc/fpvos/wifi-ap is read as text, as kestrel reads it, never run."""

    def setUp(self):
        text = WIFI.read_text()
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.d = Path(temp.name)
        (self.d / 'bin').mkdir()
        (self.d / 'address').write_text('00:11:22:33:ee:ff\n')
        body = ''.join(function(text, n) for n in
                       ('log', 'ident_key', 'ssid_ok', 'passphrase_ok', 'identity'))
        body = body.replace('/sys/class/net/wlan0/address', str(self.d / 'address'))
        (self.d / 'identity.sh').write_text(
            f'IDENT="$1"\n{body}identity\nprintf "%s\\n%s\\n" "$SSID" "$PASSPHRASE" > "$2"\n')
        # A command named after a word that must never run.
        for name in ('Goggle', 'touch'):
            p = self.d / 'bin' / name
            p.write_text(f'#!/bin/sh\necho ran > "{self.d}/ran-{name}"\n'); p.chmod(0o755)
        self.ident = self.d / 'etc/fpvos/wifi-ap'

    def identity(self, content=None):
        if content is not None:
            self.ident.parent.mkdir(parents=True, exist_ok=True)
            self.ident.write_bytes(content.encode() if isinstance(content, str) else content)
        out = self.d / 'out'
        r = subprocess.run(['sh', str(self.d / 'identity.sh'), str(self.ident), str(out)],
                           env=dict(os.environ, PATH=f'{self.d}/bin:/usr/bin:/bin', LC_ALL='C'),
                           capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.log = r.stdout.decode()
        self.assertEqual(list(self.d.glob('ran-*')), [], 'the file was run as shell')
        ssid, passphrase = out.read_bytes().decode().split('\n')[:2]
        return ssid, passphrase

    def test_first_start_writes_the_default(self):
        self.assertEqual(self.identity(), ('fpvOS-EEFF', '12345678'))
        self.assertEqual(self.ident.read_text(), 'SSID=fpvOS-EEFF\nPASSPHRASE=12345678\n')
        self.assertEqual(self.ident.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.log, '')

    def test_an_edited_file_is_taken_as_written(self):
        content = 'SSID=My Goggle\nPASSPHRASE=a $HOME `touch x` $(touch y) ;|&\\"\'\n'
        self.assertEqual(self.identity(content),
                         ('My Goggle', 'a $HOME `touch x` $(touch y) ;|&\\"\''))
        self.assertEqual(self.ident.read_text(), content)        # left alone
        self.assertEqual(self.log, '')

    def test_the_first_line_of_each_wins_as_in_kestrel(self):
        self.assertEqual(self.identity('# x\nSSID=one\nSSID=two\nPASSPHRASE=abcdefgh\n'),
                         ('one', 'abcdefgh'))

    def test_an_empty_file_is_written_afresh(self):
        self.assertEqual(self.identity(''), ('fpvOS-EEFF', '12345678'))
        self.assertEqual(self.ident.read_text(), 'SSID=fpvOS-EEFF\nPASSPHRASE=12345678\n')
        self.assertIn('no usable SSID', self.log)
        self.assertIn('no usable PASSPHRASE', self.log)

    def test_a_damaged_file_is_written_afresh(self):
        self.assertEqual(self.identity(b'\x00\xff\x13garbage'), ('fpvOS-EEFF', '12345678'))

    def test_only_the_unusable_value_is_replaced(self):
        self.assertEqual(self.identity('SSID=Mine\nPASSPHRASE=1234567\n'), ('Mine', '12345678'))
        self.assertEqual(self.ident.read_text(), 'SSID=Mine\nPASSPHRASE=12345678\n')
        self.assertNotIn('SSID (', self.log)
        self.assertIn('no usable PASSPHRASE', self.log)

    def test_ssid_length_in_bytes(self):
        self.assertEqual(self.identity(f'SSID={"x" * 32}\nPASSPHRASE=12345678\n')[0], 'x' * 32)
        self.assertEqual(self.identity(f'SSID={"x" * 33}\nPASSPHRASE=12345678\n')[0], 'fpvOS-EEFF')
        self.assertEqual(self.identity('SSID=Gögglé\nPASSPHRASE=12345678\n')[0], 'Gögglé')
        self.assertEqual(self.identity(f'SSID={"é" * 17}\nPASSPHRASE=12345678\n')[0], 'fpvOS-EEFF')
        self.assertEqual(self.identity('SSID=\nPASSPHRASE=12345678\n')[0], 'fpvOS-EEFF')
        self.assertEqual(self.identity('SSID=a\tb\nPASSPHRASE=12345678\n')[0], 'fpvOS-EEFF')

    def test_passphrase_is_8_to_63_printable_ascii(self):
        p63, p64 = '~' * 63, ' ' * 64
        self.assertEqual(self.identity(f'SSID=s\nPASSPHRASE={p63}\n')[1], p63)
        self.assertEqual(self.identity(f'SSID=s\nPASSPHRASE={p64}\n')[1], '12345678')
        self.assertEqual(self.identity('SSID=s\nPASSPHRASE=pässwörd\n')[1], '12345678')
        self.assertEqual(self.identity('SSID=s\r\nPASSPHRASE=12345678\r\n'), ('fpvOS-EEFF', '12345678'))

    def test_nothing_sources_the_file(self):
        self.assertNotRegex(WIFI.read_text(), r'(^|[;&|]\s*)\.\s+"?\$IDENT|source\s')

    def test_hostapd_conf_carries_the_values_verbatim(self):
        start = function(WIFI.read_text(), 'start')
        heredoc = re.search(r'^    cat > "\$RUN/hostapd.conf" <<EOF\n.*?^EOF\n', start, re.S | re.M).group(0)
        (self.d / 'run').mkdir()
        script = self.d / 'conf.sh'
        script.write_text('RUN="$1"; SSID="$2"; PASSPHRASE="$3"; ch=11\n' + heredoc)
        ssid, passphrase = 'My `touch a` Goggle', 'x$(touch b)$HOME;#'
        subprocess.run(['sh', str(script), str(self.d / 'run'), ssid, passphrase], check=True,
                       env=dict(os.environ, PATH=f'{self.d}/bin:/usr/bin:/bin'))
        conf = (self.d / 'run/hostapd.conf').read_text().splitlines()
        self.assertIn(f'ssid={ssid}', conf)
        self.assertIn(f'wpa_passphrase={passphrase}', conf)
        self.assertIn('channel=11', conf)
        self.assertEqual(list(self.d.glob('ran-*')), [])


if __name__ == '__main__':
    unittest.main()
