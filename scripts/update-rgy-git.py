#!/usr/bin/env python3
"""Update the ``rgy-git`` manifest -- the source build, from the mirror's tip.

The package builds the tree from source on the machine that installs it, so
there is no release archive to pin: the source IS the mirror's live tree.
The manifest therefore carries the tarball of that tree and its digest, and
the version names the tree: the release the tree carries, the date of the
commit and its short sha.

The version's shape is the AUR's ``rgy-search-git`` -- ``r<date>.r<sha>`` --
because it is the same source and the same question: which tree is this?
The base release comes from the tree's own manifest, and the page rule is
the tree's own: the three-number page when the tree has one, and the
highest page of the line when it does not.

Nothing here downloads a binary: the tarball is the source, and the digest
is over the source.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, List, Tuple

SCRIPTS_DIR = Path(__file__).parent
sys.path.append(str(SCRIPTS_DIR))

from git_helpers import maybe_auto_commit  # noqa: E402

try:
    import requests
except ImportError:
    requests = None

SOFTWARE_NAME = "rgy-git"
REPO = "danalec/rgy"
TARBALL_URL = f"https://github.com/{REPO}/archive/refs/heads/main.tar.gz"
COMMIT_URL = f"https://api.github.com/repos/{REPO}/commits/main"
TREE_URL = f"https://api.github.com/repos/{REPO}/contents"
BUCKET_FILE = SCRIPTS_DIR.parent / "bucket" / "rgy-git.json"
CARGO_MANIFEST = "bins/searchctl/Cargo.toml"

CARGO_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
PAGE_RE = re.compile(r"^release-(?P<base>\d+\.\d+\.\d+)(?:\.(?P<fix>\d+))?\.md$")


def _get_json(url: str, timeout: int = 30) -> Any:
    """Fetch and decode a JSON document."""
    response = requests.get(url, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
    response.raise_for_status()
    return response.json()


def _get_text(url: str, timeout: int = 30) -> str:
    """Fetch a file through the contents API and return its text."""
    payload = _get_json(url)
    return base64.b64decode(payload["content"]).decode("utf-8")


def calculate_sha256(url: str) -> str:
    """Download the source tarball and compute its digest."""
    response = requests.get(url, stream=True, timeout=120)
    response.raise_for_status()
    hasher = hashlib.sha256()
    for chunk in response.iter_content(chunk_size=65536):
        hasher.update(chunk)
    return hasher.hexdigest()


def base_version() -> str:
    """The three-number version the tree's own manifest carries."""
    manifest = _get_text(f"{TREE_URL}/{CARGO_MANIFEST}?ref=main")
    match = CARGO_VERSION_RE.search(manifest)
    if not match:
        raise ValueError("no version in the tree's Cargo.toml")
    return match.group(1)


def release_version(base: str, pages: List[str]) -> str:
    """The release the tree carries: the three-number page, or the highest of the line.

    This is the tree's own rule, in ``scripts/lib/version.ps1``: a page named
    after the base wins, and without one the highest numbered page of the
    line is the release.
    """
    if f"release-{base}.md" in pages:
        return base
    fixes: List[int] = []
    for name in pages:
        match = PAGE_RE.match(name)
        if not match or match.group("base") != base:
            continue
        if match.group("fix") is not None:
            fixes.append(int(match.group("fix")))
    if not fixes:
        raise ValueError(f"the tree carries no page for {base}")
    return f"{base}.{max(fixes)}"


def tree_identity() -> Tuple[str, str, str]:
    """The release, the date and the short sha of the tree the mirror carries."""
    commit = _get_json(COMMIT_URL)
    sha = commit["sha"]
    date = commit["commit"]["committer"]["date"][:10].replace("-", "")
    docs = _get_json(f"{TREE_URL}/docs?ref=main")
    pages = [entry["name"] for entry in docs]
    base = base_version()
    return release_version(base, pages), date, sha[:7]


def update_manifest(force: bool = False) -> bool:
    """Bring the manifest to the mirror's tip. Returns True when it succeeded."""
    structured_only = os.environ.get("STRUCTURED_ONLY") == "1"
    if not structured_only:
        print(f"🔄 Updating {SOFTWARE_NAME}...")

    if requests is None:
        if not structured_only:
            print("❌ requests module not installed")
        print(
            json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "requests_not_installed"})
        )
        return False

    try:
        release, date, sha = tree_identity()
    except Exception as error:
        if not structured_only:
            print(f"❌ Failed to read the mirror's tip: {error}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": str(error)}))
        return False

    version = f"{release}+r{date}.{sha}"

    try:
        with open(BUCKET_FILE, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except FileNotFoundError:
        if not structured_only:
            print(f"❌ Manifest file not found: {BUCKET_FILE}")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "manifest_not_found"}))
        return False
    except json.JSONDecodeError as error:
        if not structured_only:
            print(f"❌ Invalid JSON in manifest: {error}")
        print(
            json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": "invalid_manifest_json"})
        )
        return False

    if manifest.get("version") == version and not force:
        if not structured_only:
            print(f"✅ {SOFTWARE_NAME} is already up to date (v{version})")
        print(json.dumps({"updated": False, "name": SOFTWARE_NAME, "version": version}))
        return True

    if not structured_only:
        print(f"📥 The mirror carries {version}. Hashing the source tarball...")

    try:
        digest = calculate_sha256(TARBALL_URL)
    except Exception as error:
        if not structured_only:
            print(f"❌ Failed to download and hash the source: {error}")
        print(
            json.dumps({"updated": False, "name": SOFTWARE_NAME, "error": f"hash_failed: {error}"})
        )
        return False

    manifest["version"] = version
    manifest["url"] = TARBALL_URL
    manifest["hash"] = f"sha256:{digest}"

    with open(BUCKET_FILE, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    if not structured_only:
        print(f"✅ Updated {SOFTWARE_NAME}: {version}")
    print(json.dumps({"updated": True, "name": SOFTWARE_NAME, "version": version}))
    maybe_auto_commit(SOFTWARE_NAME, str(BUCKET_FILE), sys.argv)
    return True


def main() -> int:
    force = "--force" in sys.argv
    if not update_manifest(force):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
