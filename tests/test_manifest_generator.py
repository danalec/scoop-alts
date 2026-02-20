"""Tests for manifest_generator module."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def load_manifest_generator():
    """Load manifest_generator module dynamically."""
    mg_path = Path(__file__).parent.parent / "scripts" / "manifest-generator.py"
    spec = importlib.util.spec_from_file_location("manifest_generator", str(mg_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


def load_version_detector():
    """Load version_detector module dynamically."""
    vd_path = Path(__file__).parent.parent / "scripts" / "version_detector.py"
    spec = importlib.util.spec_from_file_location("version_detector", str(vd_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    return mod


@pytest.fixture
def manifest_generator():
    """Provide manifest_generator module for testing."""
    return load_manifest_generator()


@pytest.fixture
def version_detector():
    """Provide version_detector module for testing."""
    return load_version_detector()


@pytest.fixture
def temp_bucket_dir(tmp_path):
    """Create a temporary bucket directory."""
    bucket_dir = tmp_path / "bucket"
    bucket_dir.mkdir()
    return bucket_dir


@pytest.fixture
def sample_config(version_detector):
    """Provide a sample SoftwareConfig for testing."""
    return version_detector.SoftwareConfig(
        name="test-package",
        description="A test package for unit testing",
        homepage="https://example.com/releases",
        version_regex=r'"tag_name":\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"',
        download_url_template="https://example.com/releases/download/v$version/test-$version.exe",
        license="MIT",
        bin_name="test.exe",
        shortcuts=[["test.exe", "Test Package"]],
    )


class TestManifestGenerator:
    """Tests for ManifestGenerator class."""
    
    def test_init_default_bucket_dir(self, manifest_generator):
        """Test ManifestGenerator initialization with default bucket dir."""
        mg = manifest_generator.ManifestGenerator()
        
        assert mg.bucket_dir is not None
        assert mg.bucket_dir.name == "bucket"
    
    def test_init_custom_bucket_dir(self, manifest_generator, temp_bucket_dir):
        """Test ManifestGenerator initialization with custom bucket dir."""
        mg = manifest_generator.ManifestGenerator(bucket_dir=temp_bucket_dir)
        
        assert mg.bucket_dir == temp_bucket_dir
    
    def test_detector_initialized(self, manifest_generator):
        """Test that VersionDetector is initialized."""
        mg = manifest_generator.ManifestGenerator()
        
        assert mg.detector is not None


class TestFetchVersionInfoLegacy:
    """Tests for fetch_version_info_legacy method."""
    
    def test_fetch_version_info_legacy_success(self, manifest_generator, version_detector, sample_config):
        """Test successful version fetch using legacy method."""
        mg = manifest_generator.ManifestGenerator()
        
        # Mock the HTTP response
        mock_response = MagicMock()
        mock_response.text = '{"tag_name": "v1.2.3"}'
        mock_response.raise_for_status = MagicMock()
        
        with patch.object(mg.detector.session, 'get', return_value=mock_response):
            version, url = mg.fetch_version_info_legacy(sample_config)
            
            assert version == "1.2.3"
            assert "1.2.3" in url
    
    def test_fetch_version_info_legacy_version_not_found(self, manifest_generator, version_detector, sample_config):
        """Test version fetch when regex doesn't match."""
        mg = manifest_generator.ManifestGenerator()
        
        # Mock the HTTP response with no matching version
        mock_response = MagicMock()
        mock_response.text = '{"name": "no version here"}'
        mock_response.raise_for_status = MagicMock()
        
        with patch.object(mg.detector.session, 'get', return_value=mock_response):
            with pytest.raises(Exception) as exc_info:
                mg.fetch_version_info_legacy(sample_config)
            
            assert "Version not found" in str(exc_info.value)
    
    def test_fetch_version_info_legacy_network_error(self, manifest_generator, version_detector, sample_config):
        """Test version fetch when network request fails."""
        mg = manifest_generator.ManifestGenerator()
        
        with patch.object(mg.detector.session, 'get', side_effect=Exception("Network error")):
            with pytest.raises(Exception) as exc_info:
                mg.fetch_version_info_legacy(sample_config)
            
            assert "Failed to fetch version info" in str(exc_info.value)


class TestGenerateManifest:
    """Tests for generate_manifest method."""
    
    def test_generate_manifest_basic(self, manifest_generator, version_detector, sample_config, temp_bucket_dir):
        """Test basic manifest generation."""
        mg = manifest_generator.ManifestGenerator(bucket_dir=temp_bucket_dir)
        
        # Mock version_info response
        mock_version_info = {
            'version': '1.2.3',
            'download_url': 'https://example.com/releases/download/v1.2.3/test-1.2.3.exe',
            'hash': 'abc123def456'
        }
        
        with patch.object(manifest_generator, 'get_version_info', return_value=mock_version_info):
            manifest = mg.generate_manifest(sample_config)
            
            assert manifest['version'] == '1.2.3'
            assert manifest['description'] == sample_config.description
            assert manifest['homepage'] == sample_config.homepage
            assert manifest['license'] == sample_config.license
            assert 'url' in manifest
            assert 'hash' in manifest
            assert manifest['hash'].startswith('sha256:')
    
    def test_generate_manifest_with_bin_name(self, manifest_generator, version_detector, sample_config, temp_bucket_dir):
        """Test manifest generation with bin name."""
        mg = manifest_generator.ManifestGenerator(bucket_dir=temp_bucket_dir)
        
        mock_version_info = {
            'version': '1.2.3',
            'download_url': 'https://example.com/test-1.2.3.exe',
            'hash': 'abc123'
        }
        
        with patch.object(manifest_generator, 'get_version_info', return_value=mock_version_info):
            manifest = mg.generate_manifest(sample_config)
            
            assert 'bin' in manifest
            assert manifest['bin'] == 'test.exe'
    
    def test_generate_manifest_with_shortcuts(self, manifest_generator, version_detector, sample_config, temp_bucket_dir):
        """Test manifest generation with shortcuts."""
        mg = manifest_generator.ManifestGenerator(bucket_dir=temp_bucket_dir)
        
        mock_version_info = {
            'version': '1.2.3',
            'download_url': 'https://example.com/test-1.2.3.exe',
            'hash': 'abc123'
        }
        
        with patch.object(manifest_generator, 'get_version_info', return_value=mock_version_info):
            manifest = mg.generate_manifest(sample_config)
            
            assert 'shortcuts' in manifest
            assert len(manifest['shortcuts']) == 1
            assert manifest['shortcuts'][0][1] == "Test Package"
    
    def test_generate_manifest_with_extract_dir(self, manifest_generator, version_detector, temp_bucket_dir):
        """Test manifest generation with extract directory."""
        config = version_detector.SoftwareConfig(
            name="test-package",
            description="Test package",
            homepage="https://example.com",
            version_regex=r'([0-9]+\.[0-9]+)',
            download_url_template="https://example.com/test-$version.zip",
            license="MIT",
            extract_dir="test-$version"
        )
        
        mg = manifest_generator.ManifestGenerator(bucket_dir=temp_bucket_dir)
        
        mock_version_info = {
            'version': '1.2.3',
            'download_url': 'https://example.com/test-1.2.3.zip',
            'hash': 'abc123'
        }
        
        with patch.object(manifest_generator, 'get_version_info', return_value=mock_version_info):
            manifest = mg.generate_manifest(config)
            
            assert 'extract_dir' in manifest
            assert '1.2.3' in manifest['extract_dir']
    
    def test_generate_manifest_with_post_install(self, manifest_generator, version_detector, temp_bucket_dir):
        """Test manifest generation with post_install scripts."""
        config = version_detector.SoftwareConfig(
            name="test-package",
            description="Test package",
            homepage="https://example.com",
            version_regex=r'([0-9]+\.[0-9]+)',
            download_url_template="https://example.com/test-$version.exe",
            license="MIT",
            post_install=["echo 'Installing version $version'"]
        )
        
        mg = manifest_generator.ManifestGenerator(bucket_dir=temp_bucket_dir)
        
        mock_version_info = {
            'version': '1.2.3',
            'download_url': 'https://example.com/test-1.2.3.exe',
            'hash': 'abc123'
        }
        
        with patch.object(manifest_generator, 'get_version_info', return_value=mock_version_info):
            manifest = mg.generate_manifest(config)
            
            assert 'post_install' in manifest
            assert '1.2.3' in manifest['post_install'][0]


class TestSaveManifest:
    """Tests for save_manifest method."""
    
    def test_save_manifest_success(self, manifest_generator, version_detector, temp_bucket_dir):
        """Test saving a manifest to file."""
        mg = manifest_generator.ManifestGenerator(bucket_dir=temp_bucket_dir)
        
        config = version_detector.SoftwareConfig(
            name="test-package",
            description="Test package",
            homepage="https://example.com",
            version_regex=r"([0-9]+\.[0-9]+)",
            download_url_template="https://example.com/test-$version.exe",
            license="MIT"
        )
        
        manifest = {
            "version": "1.0.0",
            "description": "Test package",
            "homepage": "https://example.com",
            "url": "https://example.com/test.exe",
            "hash": "sha256:abc123"
        }
        
        mg.save_manifest(config, manifest)
        
        manifest_path = temp_bucket_dir / "test-package.json"
        assert manifest_path.exists()
        
        with open(manifest_path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        
        assert loaded == manifest
    
    def test_save_manifest_creates_directory(self, manifest_generator, version_detector, tmp_path):
        """Test that save_manifest works when bucket directory exists."""
        bucket_dir = tmp_path / "new_bucket"
        bucket_dir.mkdir(parents=True, exist_ok=True)  # Create directory first
        mg = manifest_generator.ManifestGenerator(bucket_dir=bucket_dir)
        
        config = version_detector.SoftwareConfig(
            name="test",
            description="Test",
            homepage="https://example.com",
            version_regex=r"([0-9]+\.[0-9]+)",
            download_url_template="https://example.com/test-$version.exe",
            license="MIT"
        )
        
        manifest = {
            "version": "1.0.0",
            "description": "Test",
            "homepage": "https://example.com",
            "url": "https://example.com/test.exe",
            "hash": "sha256:abc"
        }
        
        mg.save_manifest(config, manifest)
        
        assert bucket_dir.exists()
        assert (bucket_dir / "test.json").exists()


class TestLoadSoftwareConfigs:
    """Tests for load_software_configs function."""
    
    def test_load_software_configs_missing_file(self, manifest_generator, tmp_path):
        """Test loading configs from non-existent file."""
        config_path = tmp_path / "missing.json"
        
        # The function raises FileNotFoundError for missing files
        with pytest.raises(FileNotFoundError):
            manifest_generator.load_software_configs(config_path)
    
    def test_load_software_configs_valid_file(self, manifest_generator, tmp_path):
        """Test loading configs from valid file."""
        config_path = tmp_path / "configs.json"
        
        config_data = {
            "software": [
                {
                    "name": "test-package",
                    "description": "Test",
                    "homepage": "https://example.com",
                    "version_regex": r"([0-9]+\.[0-9]+)",
                    "download_url_template": "https://example.com/test-$version.exe",
                    "license": "MIT"
                }
            ]
        }
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config_data, f)
        
        result = manifest_generator.load_software_configs(config_path)
        
        assert len(result) == 1
        assert result[0].name == "test-package"
    
    def test_load_software_configs_invalid_json(self, manifest_generator, tmp_path):
        """Test loading configs from invalid JSON file."""
        config_path = tmp_path / "invalid.json"
        config_path.write_text("{ invalid json }")
        
        # The function raises JSONDecodeError for invalid JSON
        with pytest.raises(json.JSONDecodeError):
            manifest_generator.load_software_configs(config_path)
