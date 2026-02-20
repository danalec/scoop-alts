"""
Pytest configuration and shared fixtures for scoop-alts tests.

This module provides common fixtures that can be used across all test files.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# Add scripts directory to path for imports
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


# ============================================================================
# Path Fixtures
# ============================================================================

@pytest.fixture
def repo_root():
    """Provide the repository root path."""
    return Path(__file__).parent.parent


@pytest.fixture
def scripts_dir(repo_root):
    """Provide the scripts directory path."""
    return repo_root / "scripts"


@pytest.fixture
def bucket_dir(repo_root):
    """Provide the bucket directory path."""
    return repo_root / "bucket"


@pytest.fixture
def temp_bucket_dir(tmp_path):
    """Create a temporary bucket directory for testing."""
    bucket_dir = tmp_path / "bucket"
    bucket_dir.mkdir()
    return bucket_dir


@pytest.fixture
def temp_scripts_dir(tmp_path):
    """Create a temporary scripts directory for testing."""
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    return scripts_dir


# ============================================================================
# Manifest Fixtures
# ============================================================================

@pytest.fixture
def sample_manifest():
    """Provide a sample Scoop manifest for testing."""
    return {
        "version": "1.2.3",
        "description": "A sample application for testing",
        "homepage": "https://example.com",
        "license": "MIT",
        "url": "https://example.com/downloads/app-1.2.3.exe",
        "hash": "sha256:abc123def456789012345678901234567890123456789012345678901234567890",
        "bin": "app.exe",
        "shortcuts": [
            ["app.exe", "Sample App"]
        ]
    }


@pytest.fixture
def sample_manifest_with_architecture():
    """Provide a sample manifest with architecture-specific configuration."""
    return {
        "version": "2.0.0",
        "description": "Architecture-aware application",
        "homepage": "https://example.com",
        "license": "Apache-2.0",
        "architecture": {
            "64bit": {
                "url": "https://example.com/app-2.0.0-x64.exe",
                "hash": "sha256:aaa111bbb222ccc333ddd444eee555fff666777888999000111222333444555666"
            },
            "32bit": {
                "url": "https://example.com/app-2.0.0-x86.exe",
                "hash": "sha256:bbb222ccc333ddd444eee555fff666777888999000111222333444555666777888"
            }
        },
        "bin": "app.exe"
    }


@pytest.fixture
def sample_manifest_with_persist():
    """Provide a sample manifest with persist configuration."""
    return {
        "version": "3.0.0",
        "description": "Application with persisted data",
        "homepage": "https://example.com",
        "license": "GPL-3.0",
        "url": "https://example.com/app-3.0.0.zip",
        "hash": "sha256:ccc333ddd444eee555fff666777888999000111222333444555666777888999000",
        "extract_dir": "app-3.0.0",
        "bin": "app.exe",
        "persist": "data"
    }


@pytest.fixture
def temp_manifest_file(tmp_path, sample_manifest):
    """Create a temporary manifest file for testing."""
    bucket_dir = tmp_path / "bucket"
    bucket_dir.mkdir()
    manifest_path = bucket_dir / "test-app.json"
    
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(sample_manifest, f, indent=2)
    
    return manifest_path


# ============================================================================
# Config Fixtures
# ============================================================================

@pytest.fixture
def sample_software_config():
    """Provide a sample software configuration for testing."""
    return {
        "name": "test-package",
        "description": "A test package for unit testing",
        "homepage": "https://api.github.com/repos/test/test-package/releases/latest",
        "version_regex": r'"tag_name":\s*"v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)"',
        "download_url_template": "https://github.com/test/test-package/releases/download/v$version/test-$version.exe",
        "license": "MIT",
        "bin_name": "test.exe",
        "shortcuts": [["test.exe", "Test Package"]]
    }


@pytest.fixture
def sample_software_configs_file(tmp_path, sample_software_config):
    """Create a temporary software-configs.json file for testing."""
    config_file = tmp_path / "software-configs.json"
    
    config_data = {
        "software": [sample_software_config]
    }
    
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2)
    
    return config_file


# ============================================================================
# HTTP Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_github_release_response():
    """Provide a mock GitHub release API response."""
    return {
        "tag_name": "v1.2.3",
        "name": "Release 1.2.3",
        "html_url": "https://github.com/test/test-package/releases/tag/v1.2.3",
        "assets": [
            {
                "name": "test-1.2.3.exe",
                "browser_download_url": "https://github.com/test/test-package/releases/download/v1.2.3/test-1.2.3.exe",
                "size": 1024000
            }
        ]
    }


@pytest.fixture
def mock_http_response():
    """Create a mock HTTP response object."""
    def _create_mock(status_code=200, json_data=None, text="", headers=None):
        mock = MagicMock()
        mock.status_code = status_code
        mock.json.return_value = json_data or {}
        mock.text = text
        mock.headers = headers or {}
        mock.raise_for_status = MagicMock()
        
        if status_code >= 400:
            mock.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
        
        return mock
    return _create_mock


# ============================================================================
# Git Mock Fixtures
# ============================================================================

@pytest.fixture
def mock_git_repo(tmp_path):
    """Create a mock git repository for testing."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    
    # Initialize git repo
    os.system(f'cd "{repo_dir}" && git init')
    os.system(f'cd "{repo_dir}" && git config user.email "test@test.com"')
    os.system(f'cd "{repo_dir}" && git config user.name "Test User"')
    
    # Create initial commit
    test_file = repo_dir / "README.md"
    test_file.write_text("# Test Repository")
    os.system(f'cd "{repo_dir}" && git add README.md')
    os.system(f'cd "{repo_dir}" && git commit -m "Initial commit"')
    
    return repo_dir


# ============================================================================
# Version Detection Fixtures
# ============================================================================

@pytest.fixture
def mock_version_info():
    """Provide mock version information."""
    return {
        "version": "1.2.3",
        "download_url": "https://example.com/downloads/app-1.2.3.exe",
        "hash": "abc123def456789012345678901234567890123456789012345678901234567890"
    }


# ============================================================================
# Utility Functions
# ============================================================================

def load_module_from_path(module_name: str, file_path: Path):
    """
    Dynamically load a Python module from a file path.
    
    Args:
        module_name: Name to give the loaded module
        file_path: Path to the Python file
    
    Returns:
        The loaded module object
    """
    import importlib.util
    
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {file_path}")
    
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def load_module():
    """Provide the load_module_from_path function as a fixture."""
    return load_module_from_path


# ============================================================================
# Skip Markers
# ============================================================================

def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "network: marks tests that require network access"
    )
    config.addinivalue_line(
        "markers", "windows: marks tests that only run on Windows"
    )
    config.addinivalue_line(
        "markers", "linux: marks tests that only run on Linux"
    )
