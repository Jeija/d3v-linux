import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from d3v_linux.device import BOOT_DESCRIPTOR, Device, bound_bootloader, discover, prepare


def device(mode="audio", port="1-2"):
    return Device(
        "/dev/hidraw3",
        port,
        "/sys/devices/usb1/" + port,
        "ADAM Audio D3V" if mode == "audio" else "WPM USB",
        mode,
        BOOT_DESCRIPTOR,
    )


class DeviceTests(unittest.TestCase):
    def test_same_port_required(self):
        with tempfile.TemporaryDirectory() as folder:
            prepare([device()], folder)
            self.assertEqual(bound_bootloader([device("bootloader")], folder), device("bootloader"))
            for candidates in [
                [],
                [device("bootloader", "1-3")],
                [replace(device("bootloader"), usb_path="/different/controller/1-2")],
                [replace(device("bootloader"), descriptor=b"wrong")],
            ]:
                with self.subTest(candidates=candidates), self.assertRaises(ValueError):
                    bound_bootloader(candidates, folder)

    def test_multiple_devices_need_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            devices = [device(port="1-2"), device(port="1-3")]
            with self.assertRaises(ValueError):
                prepare(devices, folder)
            self.assertEqual(prepare(devices, folder, port="1-3").port, "1-3")

    def test_bootloader_alone_cannot_be_prepared(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            prepare([device("bootloader")], folder)

    def test_shared_audio_vid_pid_does_not_identify_d3v(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            usb = root / "devices/1-2"
            hid = usb / "1-2:1.2/0003:08BB:2704.0001"
            hid.mkdir(parents=True)
            (usb / "idVendor").write_text("08bb")
            (usb / "product").write_text("Unrelated USB DAC")
            (hid / "uevent").write_text("HID_ID=0003:000008BB:00002704\n")
            (hid / "report_descriptor").write_bytes(b"audio descriptor")
            node = root / "class/hidraw/hidraw3"
            node.mkdir(parents=True)
            (node / "device").symlink_to(hid)
            self.assertEqual(discover(root / "class/hidraw"), [])
            (usb / "product").write_text("ADAM Audio D3V  \n")
            found = discover(root / "class/hidraw")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].port, "1-2")
