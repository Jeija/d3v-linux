import copy
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from d3v_linux.catalog import get_release, load_catalog, read_firmware, verify_bytes
from d3v_linux.download import HTTPSRedirectHandler, download, extract_firmware


def artifact(data, **extra):
    return dict(size=len(data), sha256=hashlib.sha256(data).hexdigest(), **extra)


def fixture():
    firmware, installer = b"test firmware", b"not executable"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("updater.exe", installer)
    data = buf.getvalue()
    release = dict(
        version="1.7",
        archive=artifact(data, url="https://example.test/update.zip"),
        installer=artifact(installer, member="updater.exe"),
        firmware=artifact(firmware, member="resources/firmware.bin"),
    )
    return data, release, firmware


class DownloadTests(unittest.TestCase):
    def test_shipped_catalog(self):
        self.assertEqual(get_release(load_catalog(), "1.7")["firmware"]["size"], 22124)

    def test_catalog_rejects_unsupported_protocol_and_unsafe_members(self):
        for section, key, value in [
            (None, "protocol", "unknown"),
            ("firmware", "member", "../../firmware.bin"),
            ("firmware", "member", "*.bin"),
            ("archive", "url", "http://example.test/file.zip"),
        ]:
            catalog = copy.deepcopy(load_catalog())
            target = catalog["releases"][0]
            if section:
                target = target[section]
            target[key] = value
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "catalog.json"
                path.write_text(json.dumps(catalog))
                with self.assertRaises(ValueError):
                    load_catalog(path)

    def test_corrupt_archive_never_reaches_extractor(self):
        data, release, _ = fixture()
        with patch("d3v_linux.download.subprocess.run") as run:
            with self.assertRaises(ValueError):
                extract_firmware(data[:-1], release, "7zz")
            run.assert_not_called()

    def test_extraction_and_cache_verification(self):
        data, release, firmware = fixture()

        def extract(command, **kwargs):
            self.assertEqual(command[:3], ["7zz", "e", "-so"])
            self.assertEqual(command[-1], "resources/firmware.bin")
            kwargs["stdout"].write(firmware)
            return subprocess.CompletedProcess(command, 0, stderr=b"")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / "official.zip"
            archive.write_bytes(data)
            with (
                patch("d3v_linux.download.find_sevenzip", return_value="7zz"),
                patch("d3v_linux.download.subprocess.run", side_effect=extract) as run,
            ):
                path = download(release, root, archive_path=archive)
                self.assertEqual(read_firmware(root, release), firmware)
                self.assertEqual(download(release, root), path)
                self.assertEqual(run.call_count, 1)
            path.write_bytes(b"damaged")
            with self.assertRaises(ValueError):
                read_firmware(root, release)
            with self.assertRaises(ValueError):
                download(release, root)

    def test_wrong_extracted_image_rejected(self):
        data, release, _ = fixture()
        with patch(
            "d3v_linux.download.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stderr=b""),
        ):
            with self.assertRaises(ValueError):
                extract_firmware(data, release, "7zz")

    def test_hash_mismatch_same_size(self):
        with self.assertRaises(ValueError):
            verify_bytes(b"abd", artifact(b"abc"), "test")

    def test_http_redirect_rejected(self):
        with self.assertRaises(ValueError):
            HTTPSRedirectHandler().redirect_request(None, None, 302, "", {}, "http://example.test/")
