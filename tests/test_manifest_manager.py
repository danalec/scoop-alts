
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
            "hash": "sha256:oldhash"
        }
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest_data, f)
            
        self.config = SoftwareVersionConfig(
            name=self.app_name,
            homepage="http://example.com",
            version_patterns=["v([0-9.]+)"],
            download_url_template="http://example.com/$version.zip",
            description="Test App",
            license="MIT"
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch('manifest_manager.get_version_info')
    def test_update_not_needed(self, mock_get_version):
        mock_get_version.return_value = {
            'version': '1.0.0',
            'download_url': 'http://example.com/1.0.0.zip',
            'hash': 'oldhash'
        }
        
        updater = ManifestUpdater(self.config, self.bucket_dir)
        result = updater.update()
        
        self.assertTrue(result)
        # Verify file content hasn't changed
        with open(self.manifest_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['version'], '1.0.0')

    @patch('manifest_manager.get_version_info')
    def test_update_success(self, mock_get_version):
        mock_get_version.return_value = {
            'version': '2.0.0',
            'download_url': 'http://example.com/2.0.0.zip',
            'hash': 'newhash'
        }
        
        updater = ManifestUpdater(self.config, self.bucket_dir)
        result = updater.update()
        
        self.assertTrue(result)
        # Verify file content changed
        with open(self.manifest_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['version'], '2.0.0')
        self.assertEqual(data['url'], 'http://example.com/2.0.0.zip')
        self.assertEqual(data['hash'], 'sha256:newhash')

if __name__ == '__main__':
    unittest.main()
