import unittest
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Add scripts to path
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.append(str(scripts_dir))

from manifest_manager import ManifestUpdater, is_forced
from version_detector import SoftwareVersionConfig


class TestIsForced(unittest.TestCase):
    def test_not_forced_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(sys, "argv", ["update-demo.py"]):
                self.assertFalse(is_forced())

    def test_force_env_var(self):
        with patch.dict(os.environ, {"FORCE": "1"}, clear=True):
            with patch.object(sys, "argv", ["update-demo.py"]):
                self.assertTrue(is_forced())

    def test_scoop_force_env_var(self):
        with patch.dict(os.environ, {"SCOOP_FORCE": "1"}, clear=True):
            with patch.object(sys, "argv", ["update-demo.py"]):
                self.assertTrue(is_forced())

    def test_force_long_flag(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(sys, "argv", ["update-demo.py", "--force"]):
                self.assertTrue(is_forced())

    def test_force_short_flag(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(sys, "argv", ["update-demo.py", "-f"]):
                self.assertTrue(is_forced())

    def test_forcedly_legacy_flags(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(sys, "argv", ["update-demo.py", "--forcedly"]):
                self.assertTrue(is_forced())
            with patch.object(sys, "argv", ["update-demo.py", "forcedly"]):
                self.assertTrue(is_forced())

    def test_force_value_other_than_one_is_ignored(self):
        with patch.dict(os.environ, {"FORCE": "0"}, clear=True):
            with patch.object(sys, "argv", ["update-demo.py"]):
                self.assertFalse(is_forced())


class TestForcedManifestUpdater(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.bucket_dir = Path(self.temp_dir.name)
        self.app_name = "test-app"
        self.manifest_path = self.bucket_dir / f"{self.app_name}.json"

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
    def test_env_force_auto_detected(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "1.0.0",
            "download_url": "http://example.com/1.0.0-new.zip",
            "hash": "forcedhash",
        }

        with patch.dict(os.environ, {"FORCE": "1"}, clear=True):
            updater = ManifestUpdater(self.config, self.bucket_dir)
            result = updater.update()

        self.assertTrue(result)
        self.assertTrue(updater.force)
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["version"], "1.0.0")
        self.assertEqual(data["url"], "http://example.com/1.0.0-new.zip")
        self.assertEqual(data["hash"], "sha256:forcedhash")

    @patch("manifest_manager.get_version_info")
    def test_cli_flag_auto_detected(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "1.0.0",
            "download_url": "http://example.com/1.0.0-new.zip",
            "hash": "forcedhash",
        }

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(sys, "argv", ["update-demo.py", "--force"]):
                updater = ManifestUpdater(self.config, self.bucket_dir)
                result = updater.update()

        self.assertTrue(result)
        self.assertTrue(updater.force)
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["url"], "http://example.com/1.0.0-new.zip")

    @patch("manifest_manager.get_version_info")
    def test_no_force_env_same_version_is_noop(self, mock_get_version):
        mock_get_version.return_value = {
            "version": "1.0.0",
            "download_url": "http://example.com/1.0.0.zip",
            "hash": "oldhash",
        }

        with patch.dict(os.environ, {}, clear=True):
            updater = ManifestUpdater(self.config, self.bucket_dir)
            result = updater.update()

        self.assertTrue(result)
        self.assertFalse(updater.force)
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["url"], "http://example.com/1.0.0.zip")


if __name__ == "__main__":
    unittest.main()
