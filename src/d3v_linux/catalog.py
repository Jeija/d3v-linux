"""Reviewed firmware releases and their exact upstream artifacts."""

import hashlib
import json
import re
from importlib.resources import files
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

PROTOCOL = "d3v-hid-v1"


def https_url(value):
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError(f"Expected an HTTPS URL without credentials: {value}")


def load_catalog(path=None):
    source = Path(path) if path else files("d3v_linux").joinpath("firmware.json")
    catalog = json.loads(source.read_text(encoding="utf-8"))
    if catalog.get("schema_version") != 1:
        raise ValueError("Unsupported firmware catalog schema")
    versions = set()
    for release in catalog["releases"]:
        version = release["version"]
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*(?:-[A-Za-z0-9.-]+)?", version):
            raise ValueError(f"Invalid firmware version: {version}")
        if version in versions:
            raise ValueError(f"Duplicate firmware version: {version}")
        versions.add(version)
        if release["protocol"] != PROTOCOL:
            raise ValueError(f"Unsupported protocol for firmware {version}")
        if release["validation"] not in ("hardware-tested", "protocol-verified"):
            raise ValueError(f"Missing validation status for firmware {version}")
        https_url(release["source_page"])
        https_url(release["archive"]["url"])
        for name in ("archive", "installer", "firmware"):
            artifact = release[name]
            if type(artifact["size"]) is not int or not 0 < artifact["size"] <= 64 * 1024**2:
                raise ValueError(f"Invalid {name} size for firmware {version}")
            if not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]):
                raise ValueError(f"Invalid {name} SHA-256 for firmware {version}")
            if name != "archive":
                member = artifact["member"]
                parts = PurePosixPath(member).parts
                if not parts or member.startswith(("/", "-")) or ".." in parts or "\\" in member:
                    raise ValueError(f"Invalid archive member: {member}")
                if any(c in member for c in "*?\x00"):
                    raise ValueError(f"Archive members must be literal paths: {member}")
    if catalog["default_version"] not in versions:
        raise ValueError("Default firmware version is missing from the catalog")
    return catalog


def get_release(catalog, version=None):
    version = version or catalog["default_version"]
    for release in catalog["releases"]:
        if release["version"] == version:
            return release
    raise ValueError(f"Unknown firmware {version}; run 'd3v releases' for available versions")


def verify_bytes(data, artifact, label):
    if len(data) != artifact["size"]:
        raise ValueError(f"{label}: expected {artifact['size']} bytes, got {len(data)}")
    if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
        raise ValueError(f"{label}: SHA-256 mismatch; refusing to use this file")


def firmware_path(cache, release):
    return Path(cache) / "firmware" / release["version"] / (release["firmware"]["sha256"] + ".bin")


def read_firmware(cache, release):
    path = firmware_path(cache, release)
    if not path.is_file():
        raise ValueError(f"Firmware is not cached; run 'd3v download {release['version']}' first")
    with path.open("rb") as stream:
        data = stream.read(release["firmware"]["size"] + 1)
    verify_bytes(data, release["firmware"], "Cached firmware")
    return data
