# Contributing to Scoop-Alts

Thank you for your interest in contributing to the scoop-alts project! This document provides guidelines and instructions for contributing.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Setup](#development-setup)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Testing Guidelines](#testing-guidelines)

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check the issue list as you might find that you don't need to create one. When you are creating a bug report, please include as many details as possible:

- **Use a clear and descriptive title**
- **Describe the exact steps to reproduce the problem**
- **Provide specific examples to demonstrate the steps**
- **Describe the behavior you observed and expected**
- **Include your environment details** (OS, Python version, etc.)

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion:

- **Use a clear and descriptive title**
- **Provide a step-by-step description of the suggested enhancement**
- **Describe the current behavior and explain the expected behavior**
- **Explain why this enhancement would be useful**

### Adding New Packages

To add a new package to the bucket:

1. Use the interactive wizard:
   ```bash
   python scripts/automate-scoop.py wizard
   ```

2. Or manually create:
   - A manifest file in `bucket/<package-name>.json`
   - An update script in `scripts/update-<package-name>.py`

3. Test the update script:
   ```bash
   python scripts/update-<package-name>.py
   ```

4. Validate the manifest:
   ```bash
   python scripts/automate-scoop.py validate
   ```

## Development Setup

### Prerequisites

- **Python 3.8+** with pip
- **Git** for version control
- **Scoop** (optional, for local testing)

### Initial Setup

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/scoop-alts.git
   cd scoop-alts
   ```

2. Create a virtual environment:
   ```bash
   python -m venv .venv
   
   # Windows
   .venv\Scripts\activate
   
   # Linux/macOS
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r scripts/requirements-automation.txt
   ```

4. Install pre-commit hooks:
   ```bash
   pre-commit install
   ```

5. Run tests to verify setup:
   ```bash
   pytest tests/ -v
   ```

## Pull Request Process

1. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following the coding standards below.

3. **Run tests and linting**:
   ```bash
   # Run tests
   pytest tests/ -v
   
   # Run linting
   black --check scripts/ tests/
   ruff check scripts/ tests/
   flake8 scripts/ tests/
   ```

4. **Commit your changes** with clear commit messages:
   ```
   <type>: <description>
   
   # Types: feat, fix, docs, style, refactor, test, chore
   # Example: feat: add support for new-package
   ```

5. **Push to your fork** and create a pull request.

6. **Ensure CI passes** on your pull request.

7. **Wait for review** from maintainers.

### Pull Request Checklist

- [ ] Code follows the project's coding standards
- [ ] Tests pass locally
- [ ] New tests added for new functionality
- [ ] Documentation updated if needed
- [ ] Commit messages are clear and descriptive
- [ ] PR description explains the change and motivation

## Coding Standards

### Python Style

- Follow [PEP 8](https://pep8.org/) style guidelines
- Use **Black** for formatting (line length: 100)
- Use **type hints** where appropriate
- Write **docstrings** for public functions and classes

### Code Organization

```
scripts/
├── automate-scoop.py      # Main CLI entry point
├── update-all.py          # Update orchestrator
├── version_detector.py    # Shared version detection
├── manifest-generator.py  # Manifest generation
├── git_helpers.py         # Git utilities
├── summary_utils.py       # Summary utilities
└── update-*.py            # Individual update scripts
```

### Naming Conventions

- **Files**: `lowercase-with-hyphens.py`
- **Classes**: `PascalCase`
- **Functions/Variables**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`

### Example Update Script

```python
#!/usr/bin/env python3
"""
Package Name Update Script
Automatically checks for updates and updates the Scoop manifest.
"""

import json
import sys
from pathlib import Path
from version_detector import SoftwareVersionConfig, get_version_info

SOFTWARE_NAME = "package-name"
HOMEPAGE_URL = "https://api.github.com/repos/owner/repo/releases/latest"
DOWNLOAD_URL_TEMPLATE = "https://github.com/owner/repo/releases/download/v$version/package-$version.exe"
BUCKET_FILE = Path(__file__).parent.parent / "bucket" / "package-name.json"


def update_manifest():
    """Update the Scoop manifest using shared version detection."""
    config = SoftwareVersionConfig(
        name=SOFTWARE_NAME,
        homepage=HOMEPAGE_URL,
        version_patterns=['"tag_name":\\s*"v?([\\d.]+)"'],
        download_url_template=DOWNLOAD_URL_TEMPLATE,
    )
    
    version_info = get_version_info(config)
    if not version_info:
        print(f"❌ Failed to get version info for {SOFTWARE_NAME}")
        return False
    
    # ... rest of update logic
    return True


if __name__ == "__main__":
    sys.exit(0 if update_manifest() else 1)
```

## Testing Guidelines

### Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_version_detector.py -v

# Run with coverage
pytest tests/ --cov=scripts --cov-report=html
```

### Writing Tests

- Place tests in the `tests/` directory
- Name test files as `test_*.py`
- Use descriptive test function names: `test_<function>_<scenario>_<expected>`
- Use pytest fixtures for common setup

### Test Structure

```python
import pytest
from pathlib import Path


@pytest.fixture
def sample_config():
    """Provide a sample configuration for testing."""
    return {"name": "test-package"}


def test_function_success_case(sample_config):
    """Test that function works correctly with valid input."""
    # Arrange
    expected = "expected_value"
    
    # Act
    result = function_under_test(sample_config)
    
    # Assert
    assert result == expected
```

## Questions?

If you have questions about contributing, feel free to:

1. Open a [GitHub Discussion](https://github.com/danalec/scoop-alts/discussions)
2. Ask in a GitHub Issue

Thank you for contributing! 🎉
