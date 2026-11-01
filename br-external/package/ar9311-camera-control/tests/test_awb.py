"""Exercise the source AWB estimator without vendor fixtures or hardware."""
import ctypes
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]


class State(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint) for name in
                ("red", "blue", "anchor_red", "anchor_blue", "r", "g1", "g2", "b")]


class WhiteBalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        lib = Path(cls.tmp.name) / "awb.so"
        subprocess.run(["cc", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                        str(PACKAGE / "awb.c"), "-lm", "-o", str(lib)], check=True)
        cls.lib = ctypes.CDLL(str(lib))
        cls.lib.awb_update.argtypes = [ctypes.POINTER(State), ctypes.c_void_p]
        cls.lib.awb_update.restype = ctypes.c_uint

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.state = State(313, 807, 313, 807, 1, 0, 3, 2)

    def grid(self, values=(60, 40, 24, 60), blocks=36, count=100):
        data = bytearray(36 * 512)
        for block in range(blocks):
            for cell in range(16):
                for channel, value in enumerate(values):
                    offset = block * 512 + cell * 16 + channel * 4
                    struct.pack_into("<I", data, offset, count)
                    struct.pack_into("<I", data, offset + 256, value * count)
        return ctypes.create_string_buffer(bytes(data))

    def update(self, data):
        return self.lib.awb_update(ctypes.byref(self.state), data)

    def test_neutral_converges_with_bounded_steps(self):
        data = self.grid()
        for _ in range(100):
            old = self.state.red, self.state.blue
            self.assertEqual(self.update(data), 576)
            self.assertLessEqual(abs(self.state.red - old[0]), 8)
            self.assertLessEqual(abs(self.state.blue - old[1]), 8)
        self.assertLessEqual(abs(self.state.red - 384), 2)
        self.assertLessEqual(abs(self.state.blue - 640), 2)

    def test_invalid_or_coloured_scenes_hold(self):
        for data in [self.grid(count=0), self.grid((0, 0, 0, 0)),
                     self.grid((255, 255, 255, 255)),
                     self.grid((60, 200, 10, 60)), self.grid((60, 40, 24, 100)),
                     self.grid(blocks=1), self.grid((60, 10000, 24, 60))]:
            self.assertEqual(self.update(data), 0)
            self.assertEqual((self.state.red, self.state.blue), (313, 807))

    def test_statistics_order_is_configurable(self):
        self.state.r, self.state.g1, self.state.g2, self.state.b = 0, 1, 2, 3
        for _ in range(100):
            self.update(self.grid((40, 60, 60, 24)))
        self.assertLessEqual(abs(self.state.red - 384), 2)
        self.assertLessEqual(abs(self.state.blue - 640), 2)

    def test_coloured_outliers_do_not_move_median(self):
        data = self.grid()
        # A small neutral-looking coloured region must not dominate the frame.
        for cell in range(16):
            struct.pack_into("<I", data, 256 + cell * 16 + 4, 5000)
        for _ in range(100):
            self.update(data)
        self.assertLessEqual(abs(self.state.red - 384), 2)


if __name__ == "__main__":
    unittest.main()
