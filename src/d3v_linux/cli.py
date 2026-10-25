"""Command-line interface. Downloading and inspecting never send HID reports."""

import argparse
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from . import __version__
from .catalog import get_release, load_catalog, read_firmware
from .download import download


def default_cache():
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "d3v-linux"


def parser():
    result = argparse.ArgumentParser(
        prog="d3v", description="Update ADAM Audio D3V firmware on Linux"
    )
    result.add_argument("--version", action="version", version=f"d3v-linux {__version__}")
    result.add_argument("--cache-dir", type=Path, default=default_cache())
    result.add_argument("--catalog", type=Path, help="use a reviewed alternative firmware catalog")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("releases", help="show firmware versions in the catalog")
    fetch = commands.add_parser(
        "download", help="download and extract official firmware; no USB access"
    )
    fetch.add_argument("firmware_version", nargs="?")
    fetch.add_argument("--sevenzip", help="7-Zip executable name or path")
    fetch.add_argument("--archive", type=Path, help="use an already-downloaded official ZIP")
    verify = commands.add_parser("verify", help="verify cached firmware; no USB access")
    verify.add_argument("firmware_version")
    commands.add_parser(
        "devices", help="list D3V audio devices and candidate bootloaders; no HID writes"
    )
    prepare = commands.add_parser(
        "prepare", help="remember the D3V's USB port while in normal mode"
    )
    prepare.add_argument("--port", help="choose a USB port when more than one D3V is connected")
    flash = commands.add_parser(
        "flash", help="flash a specific cached release on the selected speaker"
    )
    flash.add_argument("firmware_version", help="explicit version to install (for example, 1.7)")
    flash.add_argument("--yes", action="store_true", help="skip the interactive flash confirmation")
    return result


def run(args):
    catalog = load_catalog(args.catalog)
    if args.command == "releases":
        for release in catalog["releases"]:
            print(f"{release['version']}  {release['validation']}  {release.get('notes', '')}")
        return
    if args.command in ("download", "verify", "flash"):
        release = get_release(catalog, args.firmware_version)
    if args.command == "download":
        path = download(release, args.cache_dir, args.sevenzip, args.archive)
        print(f"Firmware {release['version']} verified and cached:\n{path}")
        return
    if args.command == "verify":
        data = read_firmware(args.cache_dir, release)
        print(f"Firmware {release['version']}: {len(data)} bytes, SHA-256 verified")
        return
    if sys.platform != "linux":
        raise ValueError("Device operations require Linux")
    from .device import Hidraw, bound_bootloader, discover, prepare
    from .updater import transfer

    devices = discover()
    if args.command == "devices":
        if not devices:
            print("No D3V audio devices or candidate bootloaders found")
        for device in devices:
            label = "D3V audio" if device.mode == "audio" else "candidate bootloader"
            print(f"{device.node}  USB {device.port}  {label}  {device.name}")
        return
    if args.command == "prepare":
        device = prepare(devices, args.cache_dir, args.port)
        print(f"Selected ADAM Audio D3V on USB port {device.port}.")
        print("Keep this USB connection. Enter update mode by holding the knob while reconnecting")
        print("mains power; release when the LED pulses purple. Then run 'd3v devices'.")
        return
    firmware = read_firmware(args.cache_dir, release)
    device = bound_bootloader(devices, args.cache_dir)
    print(f"Firmware {release['version']}: {len(firmware)} bytes, SHA-256 verified")
    print(f"Target: selected D3V on USB {device.port} ({device.node})")
    print(
        "The installed version cannot be queried. This will replace it with the selected release."
    )
    if release["validation"] != "hardware-tested":
        print("This catalog release has not yet been tested on hardware.")
    if not args.yes:
        if not sys.stdin.isatty():
            raise ValueError("Flashing needs an interactive confirmation, or --yes")
        if input("Install this firmware? [y/N] ").strip().lower() != "y":
            print("Cancelled; no USB reports sent")
            return
    log_dir = args.cache_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"flash-{time.time_ns()}.jsonl"

    def progress(done, total):
        if done == 0:
            print("Bootloader handshake verified. Keep power and USB connected.", flush=True)
        elif done % 40 == 0 or done == total:
            print(f"{done}/{total} firmware packets acknowledged", flush=True)

    # Open both device and log before the first USB write.
    with Hidraw(device) as transport, log_path.open("x", encoding="utf-8") as log:
        final_ack, log_failed = transfer(transport, firmware, log, progress)
    print(
        "Transfer complete. All packet checksums and counters matched. "
        f"Final ACK: {final_ack.hex()}"
    )
    print(f"Log: {log_path}" + (" (incomplete: a logging error occurred)" if log_failed else ""))
    print("Wait for the speaker to leave purple update mode. Then disconnect USB and mains for")
    print(
        "five seconds and reconnect without holding the knob. "
        "Run 'd3v devices' to check audio mode."
    )


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        run(args)
        return 0
    except KeyboardInterrupt:
        print("Cancelled", file=sys.stderr)
        return 130
    except (
        OSError,
        ValueError,
        KeyError,
        EOFError,
        RuntimeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
