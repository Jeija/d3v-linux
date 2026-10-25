"""Download and unpack official installers without executing them."""

import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from .catalog import firmware_path, https_url, read_firmware, verify_bytes


class HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_archive(artifact):
    https_url(artifact["url"])
    request = urllib.request.Request(artifact["url"], headers={"User-Agent": "d3v-linux/0.1"})
    opener = urllib.request.build_opener(HTTPSRedirectHandler())
    with opener.open(request, timeout=30) as response:
        data = response.read(artifact["size"] + 1)
    verify_bytes(data, artifact, "Downloaded archive")
    return data


def find_sevenzip(explicit=None):
    if explicit:
        result = shutil.which(explicit)
    else:
        result = next((p for name in ("7zz", "7z", "7za") if (p := shutil.which(name))), None)
    if not result:
        raise ValueError(
            "7-Zip was not found. Install 7zip (or p7zip-full), or pass --sevenzip PATH"
        )
    return result


def extract_firmware(archive_data, release, sevenzip):
    # Verify before passing any upstream bytes to the archive parser.
    verify_bytes(archive_data, release["archive"], "Official archive")
    with tempfile.TemporaryDirectory(prefix="d3v-extract-") as folder:
        folder = Path(folder)
        archive_path = folder / "official.zip"
        archive_path.write_bytes(archive_data)
        with zipfile.ZipFile(archive_path) as archive:
            matches = [
                i for i in archive.infolist() if i.filename == release["installer"]["member"]
            ]
            if len(matches) != 1 or matches[0].file_size != release["installer"]["size"]:
                raise ValueError("Official ZIP does not contain the expected installer")
            with archive.open(matches[0]) as stream:
                installer = stream.read(release["installer"]["size"] + 1)
        verify_bytes(installer, release["installer"], "Installer")
        installer_path = folder / "updater.exe"
        installer_path.write_bytes(installer)
        # -so selects stdout. Neither the installer nor any extracted code is executed.
        output = folder / "firmware.bin"
        with output.open("wb") as stream:
            result = subprocess.run(
                [sevenzip, "e", "-so", str(installer_path), release["firmware"]["member"]],
                stdout=stream,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
            )
        if result.returncode:
            raise ValueError(
                f"7-Zip extraction failed: {result.stderr.decode(errors='replace').strip()}"
            )
        with output.open("rb") as stream:
            firmware = stream.read(release["firmware"]["size"] + 1)
        verify_bytes(firmware, release["firmware"], "Extracted firmware")
        return firmware


def download(release, cache, sevenzip=None, archive_path=None):
    destination = firmware_path(cache, release)
    if destination.exists():
        read_firmware(cache, release)
        return destination
    executable = find_sevenzip(sevenzip)
    if archive_path:
        with Path(archive_path).open("rb") as stream:
            archive = stream.read(release["archive"]["size"] + 1)
    else:
        archive = fetch_archive(release["archive"])
    data = extract_firmware(archive, release, executable)
    destination.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            name = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, destination)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    return destination
