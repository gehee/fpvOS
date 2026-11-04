#!/usr/bin/env python3
"""Host tests: factory input is untrusted and cannot replace radio policy."""
import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
BASE = {"baseband": {"basic": {"power": {"pwr_offset": [0]*4, "pwr_init": 14},
                            "role": "ap", "channel": {"freq": [5839000]}},
                     "power_calibration": {"default": {"closeloop": {"14dbm": ["20"]*4}}}},
        "unrelated": {"keep": "value"}}
FACTORY = {"baseband": {"basic": {"power": {"pwr_offset": [-6, 2, 6, -1]}}}}


class Calibration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.build.name)/"radio-calibrate"
        flags = shlex.split(os.environ.get("JANSSON_CFLAGS", ""))
        libs = shlex.split(os.environ.get("JANSSON_LIBS", "-ljansson"))
        subprocess.run([os.environ.get("CC", "cc"), "-Wall", "-Wextra", "-Werror", *flags,
                        str(PACKAGE/"src/calibrate.c"), *libs, "-o", str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base, self.factory, self.output = [self.root/n for n in ("base", "factory", "output")]
        self.base.write_text(json.dumps(BASE))
        self.factory.write_text(json.dumps(FACTORY))

    def run_helper(self, output=None):
        return subprocess.run([str(self.binary), str(self.base), str(self.factory),
                               str(output or self.output)], capture_output=True)

    def rejected(self):
        self.output.write_text("previous complete config")
        result = self.run_helper()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.output.read_text(), "previous complete config")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["base", "factory", "output"])

    def test_merge_changes_only_offsets_and_preserves_inputs(self):
        before = [p.read_bytes() for p in (self.base, self.factory)]
        result = self.run_helper()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = copy.deepcopy(BASE)
        expected["baseband"]["basic"]["power"]["pwr_offset"] = [-6, 2, 6, -1]
        self.assertEqual(json.loads(self.output.read_text()), expected)
        self.assertEqual([p.read_bytes() for p in (self.base, self.factory)], before)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)

    def test_zero_offsets_are_valid_factory_data(self):
        self.factory.write_text(json.dumps({"baseband": {"basic": {"power": {"pwr_offset": [0]*4}}}}))
        self.assertEqual(self.run_helper().returncode, 0)

    def test_bad_values(self):
        for values in ([0]*3, [0]*5, [7,0,0,0], [-7,0,0,0], [True,0,0,0],
                       [0.0,0,0,0], ["0",0,0,0], [None,0,0,0], {}, None):
            with self.subTest(values=values):
                f = copy.deepcopy(FACTORY)
                f["baseband"]["basic"]["power"]["pwr_offset"] = values
                self.factory.write_text(json.dumps(f))
                self.rejected()

    def test_missing_wrong_or_extra_fields(self):
        for f in ({}, [], {"baseband": []}, {"baseband": {"basic": {"power": {}}}},
                  {**FACTORY, "system": {"injected": True}}):
            with self.subTest(f=f):
                self.factory.write_text(json.dumps(f))
                self.rejected()
        f = copy.deepcopy(FACTORY)
        f["baseband"]["basic"]["power"]["pwr_init"] = 39
        self.factory.write_text(json.dumps(f))
        self.rejected()

    def test_malformed_trailing_duplicate_and_oversized_inputs(self):
        for text in ('{"baseband":', json.dumps(FACTORY)+'{}',
                     '{"baseband":{},"baseband":{}}', '\0'+json.dumps(FACTORY),
                     ' '*65537+json.dumps(FACTORY)):
            with self.subTest(size=len(text)):
                self.factory.write_text(text)
                self.rejected()

    def test_invalid_base(self):
        for b in ({}, {"baseband": {"basic": {"power": []}}}, []):
            with self.subTest(b=b):
                self.base.write_text(json.dumps(b))
                self.rejected()

    def test_missing_factory(self):
        self.factory.unlink()
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_input_aliases_rejected(self):
        before = self.factory.read_bytes()
        for output in (self.base, self.factory):
            self.assertNotEqual(self.run_helper(output).returncode, 0)
        self.output.symlink_to(self.factory)
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertEqual(self.factory.read_bytes(), before)

    def test_publication_failure(self):
        self.output.mkdir()
        self.assertNotEqual(self.run_helper().returncode, 0)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["base", "factory", "output"])

    def test_ground_startup_needs_no_host_factory_data(self):
        defaults = self.root/"no-defaults"
        fw = self.root/"firmware"
        fw.mkdir()
        (fw/"open8030.img").write_text("fixture")
        (fw/"open8030.json").write_text(json.dumps(BASE))
        text = (PACKAGE/"src/S44ar9311-radio").read_text()
        text = text.replace('/etc/default/ar9311-radio', str(defaults))
        text = text.replace('/sys/module/arlink', str(self.root/'not-loaded'))
        text = text.replace('/lib/firmware', str(fw))
        binpath = self.root/"bin"
        binpath.mkdir()
        marker = self.root/"module-called"
        modprobe = binpath/"modprobe"
        modprobe.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 77\n")
        modprobe.chmod(0o755)
        script = self.root/"start"
        script.write_text(text)
        subprocess.run(['sh', str(script), 'start'], capture_output=True,
                       env={**os.environ, 'PATH': str(binpath)+':'+os.environ['PATH']})
        self.assertTrue(marker.exists())

    def test_stale_config_never_bypasses_startup_failure(self):
        self.startup(valid=False)

    def test_readonly_mount_required_before_loading(self):
        self.startup(writable=True)

    def test_valid_startup_loads_generated_config(self):
        self.startup()

    def test_wrong_loader_path_rejected(self):
        self.startup(wrong_link=True)

    def startup(self, valid=True, writable=False, wrong_link=False):
        run = self.root/"run/ar9311-radio"
        run.mkdir(parents=True)
        fw = self.root/"lib/firmware"
        fw.mkdir(parents=True)
        (fw/"open8030.img").write_text("firmware fixture")
        (run/"config.json").write_text("stale config")
        (fw/"p1.json").symlink_to(self.base if wrong_link else run/"config.json")
        mounts = self.root/"mounts"
        mounts.write_text(f"/dev/ubi0_0 /factory ubifs {'rw' if writable else 'ro'},nosuid 0 0\n")
        defaults = self.root/"defaults"
        defaults.write_text(f"config=p1.json\ncalibration_base={self.base}\n"
                            f"calibration_factory={self.factory}\ncalibration_mount=/factory\n")
        if not valid:
            self.factory.write_text('{}')
        text = (PACKAGE/"src/S44ar9311-radio").read_text()
        text = text.replace('/etc/default/ar9311-radio', str(defaults))
        text = text.replace('/usr/libexec/radio-calibrate', str(self.binary))
        for old, new in [('/sys/module/arlink', str(self.root/'not-loaded')),
                         ('/proc/mounts', str(mounts)), ('/lib/firmware', str(fw)),
                         ('/run/ar9311-radio', str(run))]:
            text = text.replace(old, new)
        # The fake module loader exits on its first call. No hardware access.
        binpath = self.root/"bin"
        binpath.mkdir()
        marker = self.root/"module-called"
        modprobe = binpath/"modprobe"
        modprobe.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 77\n")
        modprobe.chmod(0o755)
        script = self.root/"start"
        script.write_text(text)
        subprocess.run(['sh', str(script), 'start'], capture_output=True,
                       env={**os.environ, 'PATH': str(binpath)+':'+os.environ['PATH']})
        self.assertEqual(marker.exists(), valid and not writable and not wrong_link)
        if valid and not writable:
            self.assertEqual(json.loads((run/'config.json').read_text())['baseband']['basic']['power']['pwr_offset'], [-6,2,6,-1])


if __name__ == '__main__':
    unittest.main()
