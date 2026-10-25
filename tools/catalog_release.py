#!/usr/bin/env python3
"""Inspect an official ZIP and print a draft catalog entry. Never flashes USB."""

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from d3v_linux.catalog import https_url
from d3v_linux.download import HTTPSRedirectHandler, find_sevenzip

LIMIT = 64 * 1024**2


def fingerprint(data, **fields):
    return dict(fields, size=len(data), sha256=hashlib.sha256(data).hexdigest())


def inspect(args):
    https_url(args.url)
    executable = find_sevenzip(args.sevenzip)
    if args.archive:
        with args.archive.open("rb") as stream:
            data = stream.read(LIMIT + 1)
    else:
        opener = urllib.request.build_opener(HTTPSRedirectHandler())
        with opener.open(args.url, timeout=30) as stream:
            data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("Archive exceeds the 64 MiB inspection limit")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        matches = [
            i
            for i in archive.infolist()
            if (
                i.filename == args.installer_member
                if args.installer_member
                else i.filename.lower().endswith(".exe")
            )
        ]
        if len(matches) != 1:
            raise ValueError("Select exactly one installer using --installer-member")
        installer_info = matches[0]
        if not 0 < installer_info.file_size <= LIMIT:
            raise ValueError("Unexpected installer size")
        installer = archive.read(installer_info)
    with tempfile.TemporaryDirectory(prefix="d3v-inspect-") as folder:
        path = Path(folder) / "updater.exe"
        path.write_bytes(installer)
        listing = subprocess.run(
            [executable, "l", "-slt", str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
        candidates = [
            line.removeprefix("Path = ")
            for line in listing.splitlines()
            if line.startswith("Path = ") and line.endswith(".bin")
        ]
        member = args.firmware_member
        if member is None:
            if len(candidates) != 1:
                raise ValueError(
                    f"Select firmware using --firmware-member; candidates: {candidates}"
                )
            member = candidates[0]
        if member not in candidates or any(c in member for c in "*?\x00"):
            raise ValueError("Firmware member must match one literal .bin path in the installer")
        output = Path(folder) / "firmware.bin"
        with output.open("wb") as stream:
            subprocess.run(
                [executable, "e", "-so", str(path), member],
                stdout=stream,
                stderr=subprocess.PIPE,
                check=True,
                timeout=60,
            )
        with output.open("rb") as stream:
            firmware = stream.read(LIMIT + 1)
        if not 0 < len(firmware) <= LIMIT:
            raise ValueError("Unexpected firmware size")
    return {
        "version": args.version,
        "protocol": "d3v-hid-v1",
        "validation": "unreviewed",
        "source_page": "https://downloads.adam-audio.com/adam-audio/desktop/d3v",
        "notes": "",
        "archive": fingerprint(data, url=args.url),
        "installer": fingerprint(installer, member=installer_info.filename),
        "firmware": fingerprint(firmware, member=member),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--url", required=True, help="ZIP link from the official D3V download page")
    parser.add_argument("--archive", type=Path, help="inspect a local copy of that ZIP")
    parser.add_argument("--installer-member")
    parser.add_argument("--firmware-member")
    parser.add_argument("--sevenzip")
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args), indent=2))
        print(
            "Draft only: verify protocol compatibility before changing validation status.",
            file=sys.stderr,
        )
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
