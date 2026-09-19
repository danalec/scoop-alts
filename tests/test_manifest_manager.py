import unittest
import json
import tempfile
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts to path
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.append(str(scripts_dir))

from manifest_manager import ManifestUpdater
from version_detector import SoftwareVersionConfig


class TestManifestUpdater(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.bucket_dir = Path(self.temp_dir.name)
        self.app_name = "test-app"
        self.manifest_path = self.bucket_dir / f"{self.app_name}.json"

        # Create a dummy manifest
        self.manifest_data = {
            "version": "1.0.0",
            "url": "http://example.com/1.0.0.zip",
            "hash": "sha256:oldhash",
        }
        with open(self.manifest_path, "w") as f:
            json.dump(self.manifest_data, f)

        self.config = SoftwareVersionConfig(
            name=self.app_name,
            homepage="http://example.com",
            version_patterns=["v([0-9.]+)"],
            download_url_template="http://example.com/$version.zip",
            description="Test App",
            license="MIT",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("manifest_manager.get_version_info")
    def test_update_not_needed(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "1.0.0",
            "download_url": "http://example.com/1.0.0.zip",
            "hash": "oldhash",
        }

        updater = ManifestUpdater(self.config, self.bucket_dir)
        result = updater.update()

        self.assertTrue(result)
        # Verify file content hasn't changed
        with open(self.manifest_path, "r") as f:
            data = json.load(f)
        self.assertEqual(data["version"], "1.0.0")

    @patch("manifest_manager.get_version_info")
    def test_update_success(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "2.0.0",
            "download_url": "http://example.com/2.0.0.zip",
            "hash": "newhash",
        }

        updater = ManifestUpdater(self.config, self.bucket_dir)
        result = updater.update()

        self.assertTrue(result)
        # Verify file content changed
        with open(self.manifest_path, "r") as f:
            data = json.load(f)
        self.assertEqual(data["version"], "2.0.0")
        self.assertEqual(data["url"], "http://example.com/2.0.0.zip")
        self.assertEqual(data["hash"], "sha256:newhash")

    @patch("manifest_manager.get_version_info")
    def test_update_success_with_architecture_block(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "2.0.0",
            "download_url": "http://example.com/2.0.0.zip",
            "hash": "newhash",
        }

        self.manifest_data = {
            "version": "1.0.0",
            "architecture": {
                "64bit": {"url": "http://example.com/1.0.0.zip", "hash": "sha256:oldhash"}
            },
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest_data, f)

        updater = ManifestUpdater(self.config, self.bucket_dir)
        result = updater.update()

        self.assertTrue(result)
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["version"], "2.0.0")
        self.assertEqual(data["architecture"]["64bit"]["url"], "http://example.com/2.0.0.zip")
        self.assertEqual(data["architecture"]["64bit"]["hash"], "sha256:newhash")

    @patch("manifest_manager.get_version_info")
    def test_update_forced_same_version(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "1.0.0",
            "download_url": "http://example.com/1.0.0-new.zip",
            "hash": "forcedhash",
        }

        updater = ManifestUpdater(self.config, self.bucket_dir, force=True)
        result = updater.update()

        self.assertTrue(result)
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["url"], "http://example.com/1.0.0-new.zip")
        self.assertEqual(data["hash"], "sha256:forcedhash")

    @patch("manifest_manager.get_version_info")
    def test_update_passes_current_version_to_skip_hash(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "1.0.0",
            "download_url": "http://example.com/1.0.0.zip",
            "hash": None,
        }

        updater = ManifestUpdater(self.config, self.bucket_dir)
        result = updater.update()

        self.assertTrue(result)
        _, kwargs = mock_get_version.call_args
        self.assertEqual(kwargs.get("current_version"), "1.0.0")
        # Manifest untouched — no download/hash happened for the up-to-date package
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["hash"], "sha256:oldhash")

    @patch("manifest_manager.get_version_info")
    def test_update_forced_passes_no_current_version(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "1.0.0",
            "download_url": "http://example.com/1.0.0-new.zip",
            "hash": "forcedhash",
        }

        updater = ManifestUpdater(self.config, self.bucket_dir, force=True)
        result = updater.update()

        self.assertTrue(result)
        _, kwargs = mock_get_version.call_args
        self.assertIsNone(kwargs.get("current_version"))

    @patch("manifest_manager.get_version_info")
    def test_update_architecture_templates_writes_per_arch(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "2.0.0",
            "download_url": "http://example.com/2.0.0.zip",
            "hash": "unusedhash",
        }

        config = SoftwareVersionConfig(
            name=self.app_name,
            homepage="http://example.com",
            version_patterns=["v([0-9.]+)"],
            download_url_template="http://example.com/$version.zip",
            description="Test App",
            license="MIT",
            architecture_templates={
                "64bit": "http://example.com/app-$version-x64.zip",
                "arm64": "http://example.com/app-$version-arm64.zip",
            },
        )

        # Pre-existing multi-arch block plus stale top-level url/hash
        manifest_data = {
            "version": "1.0.0",
            "url": "http://example.com/1.0.0.zip",
            "hash": "sha256:oldhash",
            "architecture": {
                "64bit": {"url": "http://example.com/old-x64.zip", "hash": "sha256:old64"},
                "32bit": {"url": "http://example.com/old-x86.zip", "hash": "sha256:old32"},
            },
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

        fake_detector = MagicMock()
        fake_detector.construct_download_url.side_effect = (
            lambda template, version, match_groups=None: template.replace("$version", version)
        )
        fake_detector.calculate_hash.side_effect = lambda url: "hash-of-" + url

        with patch("manifest_manager.VersionDetector", return_value=fake_detector):
            updater = ManifestUpdater(config, self.bucket_dir)
            result = updater.update()

        self.assertTrue(result)
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["version"], "2.0.0")
        self.assertEqual(
            data["architecture"],
            {
                "64bit": {
                    "url": "http://example.com/app-2.0.0-x64.zip",
                    "hash": "sha256:hash-of-http://example.com/app-2.0.0-x64.zip",
                },
                "arm64": {
                    "url": "http://example.com/app-2.0.0-arm64.zip",
                    "hash": "sha256:hash-of-http://example.com/app-2.0.0-arm64.zip",
                },
            },
        )
        # Stale top-level fields must not survive once per-arch entries exist
        self.assertNotIn("url", data)
        self.assertNotIn("hash", data)

    @patch("manifest_manager.get_version_info")
    def test_update_arch_template_hash_failure_aborts(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "2.0.0",
            "download_url": "http://example.com/2.0.0.zip",
            "hash": "unusedhash",
        }

        config = SoftwareVersionConfig(
            name=self.app_name,
            homepage="http://example.com",
            version_patterns=["v([0-9.]+)"],
            download_url_template="http://example.com/$version.zip",
            description="Test App",
            license="MIT",
            architecture_templates={"64bit": "http://example.com/app-$version-x64.zip"},
        )

        fake_detector = MagicMock()
        fake_detector.construct_download_url.side_effect = (
            lambda template, version, match_groups=None: template.replace("$version", version)
        )
        fake_detector.calculate_hash.return_value = None

        with patch("manifest_manager.VersionDetector", return_value=fake_detector):
            updater = ManifestUpdater(config, self.bucket_dir)
            with patch("builtins.print") as mock_print:
                result = updater.update()

        self.assertFalse(result)
        payloads = [
            json.loads(call[0][0])
            for call in mock_print.call_args_list
            if call[0] and str(call[0][0]).startswith("{")
        ]
        self.assertTrue(
            any(p.get("error") == "arch_hash_failed" for p in payloads),
            payloads,
        )
        # Manifest on disk must be untouched
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["hash"], "sha256:oldhash")

    @patch("manifest_manager.get_version_info")
    def test_update_multi_arch_guard_without_templates(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "2.0.0",
            "download_url": "http://example.com/2.0.0.zip",
            "hash": "newhash",
        }

        manifest_data = {
            "version": "1.0.0",
            "architecture": {
                "64bit": {"url": "http://example.com/1.0.0-x64.zip", "hash": "sha256:old64"},
                "32bit": {"url": "http://example.com/1.0.0-x86.zip", "hash": "sha256:old32"},
            },
        }
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

        updater = ManifestUpdater(self.config, self.bucket_dir)
        with patch("builtins.print") as mock_print:
            result = updater.update()

        self.assertFalse(result)
        payloads = [
            json.loads(call[0][0])
            for call in mock_print.call_args_list
            if call[0] and str(call[0][0]).startswith("{")
        ]
        self.assertTrue(
            any(p.get("error") == "multi_arch_requires_custom_updater" for p in payloads),
            payloads,
        )

    def test_emit_result_includes_forced_flag(self):
        updater = ManifestUpdater(self.config, self.bucket_dir, force=True)
        with patch("builtins.print") as mock_print:
            updater.emit_result(updated=True, version="1.2.3", forced=updater.force)
        payload = json.loads(mock_print.call_args[0][0])
        self.assertEqual(payload["forced"], True)

    def test_emit_result_omits_forced_flag_by_default(self):
        updater = ManifestUpdater(self.config, self.bucket_dir)
        with patch("builtins.print") as mock_print:
            updater.emit_result(updated=True, version="1.2.3")
        payload = json.loads(mock_print.call_args[0][0])
        self.assertNotIn("forced", payload)

    @patch("manifest_manager.get_version_info")
    def test_update_emits_forced_flag_in_payload(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "1.0.0",
            "download_url": "http://example.com/1.0.0-new.zip",
            "hash": "forcedhash",
        }

        updater = ManifestUpdater(self.config, self.bucket_dir, force=True)
        with patch("builtins.print") as mock_print:
            result = updater.update()

        self.assertTrue(result)
        payloads = [
            json.loads(call[0][0])
            for call in mock_print.call_args_list
            if call[0] and str(call[0][0]).startswith("{")
        ]
        updated_payloads = [p for p in payloads if p.get("updated")]
        self.assertTrue(updated_payloads)
        for payload in updated_payloads:
            self.assertEqual(payload.get("forced"), True)


if __name__ == "__main__":
    unittest.main()
