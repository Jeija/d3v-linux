"""Identify the speakers in normal mode, then follow the same USB port."""

import fcntl
import json
import os
import select
import struct
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

BOOT_ID = "0003:00000416:00003F00"
AUDIO_ID = "0003:000008BB:00002704"
BOOT_DESCRIPTOR = bytes.fromhex("0600ff0901a10119012940150026ff00750895408100190129409100c0")


@dataclass(frozen=True)
class Device:
    node: str
    port: str
    usb_path: str
    name: str
    mode: str
    descriptor: bytes


def discover(sysfs=Path("/sys/class/hidraw"), dev=Path("/dev")):
    devices = []
    for node in sorted(sysfs.glob("hidraw*")):
        try:
            hid = (node / "device").resolve()
            info = dict(
                line.split("=", 1)
                for line in (hid / "uevent").read_text().splitlines()
                if "=" in line
            )
            hid_id = info.get("HID_ID")
            if hid_id not in (BOOT_ID, AUDIO_ID):
                continue
            usb = next((p for p in hid.parents if (p / "idVendor").exists()), None)
            if usb is None:
                continue
            product = (usb / "product").read_text().strip()
            if hid_id == AUDIO_ID and product != "ADAM Audio D3V":
                continue  # This USB DAC ID is shared with unrelated products.
            devices.append(
                Device(
                    node=str(dev / node.name),
                    port=usb.name,
                    usb_path=str(usb),
                    name=product,
                    mode="audio" if hid_id == AUDIO_ID else "bootloader",
                    descriptor=(hid / "report_descriptor").read_bytes(),
                )
            )
        except FileNotFoundError:
            continue  # The device may have disconnected during enumeration.
    return devices


def prepare(devices, cache, port=None):
    matches = [d for d in devices if d.mode == "audio" and (port is None or d.port == port)]
    if len(matches) != 1:
        raise ValueError("Connect one D3V in normal audio mode, or select it with --port PORT")
    device = matches[0]
    state = asdict(device)
    del state["descriptor"]
    state["schema_version"] = 1
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=cache, delete=False) as stream:
            name = stream.name
            json.dump(state, stream, indent=2)
            stream.write("\n")
        os.replace(name, cache / "device.json")
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    return device


def bound_bootloader(devices, cache):
    path = Path(cache) / "device.json"
    if not path.exists():
        raise ValueError("No speaker selected. Run 'd3v prepare' while the D3V is in normal mode")
    state = json.loads(path.read_text())
    if state.get("schema_version") != 1 or state.get("mode") != "audio":
        raise ValueError("Invalid device selection; run 'd3v prepare' again in normal mode")
    matches = [
        d
        for d in devices
        if d.mode == "bootloader" and d.usb_path == state["usb_path"] and d.port == state["port"]
    ]
    if len(matches) != 1:
        raise ValueError(
            f"No unique bootloader at USB port {state['port']}. Enter update mode on the same port"
        )
    device = matches[0]
    if device.descriptor != BOOT_DESCRIPTOR:
        raise ValueError("Unrecognized bootloader HID descriptor; this hardware needs review")
    return device


class Hidraw:
    def __init__(self, device):
        self.device = device
        self.fd = None

    def __enter__(self):
        try:
            self.fd = os.open(self.device.node, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        except PermissionError as exc:
            import getpass
            import shlex

            command = "sudo setfacl -m " + shlex.quote(f"u:{getpass.getuser()}:rw")
            command += " " + shlex.quote(self.device.node)
            raise PermissionError(
                f"Cannot open {self.device.node}. Grant temporary access:\n{command}"
            ) from exc
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            info = bytearray(8)
            fcntl.ioctl(self.fd, 0x80084803, info, True)  # HIDIOCGRAWINFO
            if struct.unpack("<IHH", info) != (3, 0x0416, 0x3F00):
                raise ValueError("The opened device is no longer the expected bootloader")
            # Recheck descriptor through the opened fd, not just the earlier sysfs snapshot.
            size = bytearray(4)
            fcntl.ioctl(self.fd, 0x80044801, size, True)  # HIDIOCGRDESCSIZE
            length = struct.unpack("<I", size)[0]
            if length != len(BOOT_DESCRIPTOR):
                raise ValueError("Opened bootloader descriptor size changed")
            descriptor = bytearray(struct.pack("<I", length) + bytes(4096))
            fcntl.ioctl(self.fd, 0x90044802, descriptor, True)  # HIDIOCGRDESC
            if descriptor[4 : 4 + length] != BOOT_DESCRIPTOR:
                raise ValueError("Opened bootloader descriptor changed")
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise
        return self

    def exchange(self, packet, length):
        if os.write(self.fd, packet) != len(packet):
            raise OSError("Short HID write; stopped without retry")
        ready, _, _ = select.select([self.fd], [], [], 5.0)
        if not ready:
            raise TimeoutError(
                "No bootloader acknowledgment within five seconds; no retry was sent"
            )
        # hidapi in the official updater also truncates each report to this buffer size.
        return os.read(self.fd, length)

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
