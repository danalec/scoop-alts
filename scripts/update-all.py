#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scoop Bucket Update Orchestrator
Runs all update scripts for the scoop-alts bucket and provides a summary report.
"""

import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime
import argparse
import concurrent.futures
import os
import json
from typing import List, Tuple, Dict
import threading
import logging

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    try:
        import codecs
        if hasattr(sys.stdout, "detach"):
            sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        if hasattr(sys.stderr, "detach"):
            sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())
    except Exception:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# Configuration
SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent

# Performance and Concurrency Constants
DEFAULT_TIMEOUT = int(os.environ.get('SCOOP_UPDATE_TIMEOUT', '120'))  # seconds per script execution
DEFAULT_WORKERS = int(os.environ.get('SCOOP_UPDATE_WORKERS', '6'))    # default parallel workers
DEFAULT_RETRY_ATTEMPTS = int(os.environ.get('SCOOP_RETRY_ATTEMPTS', '0'))  # no retries by default

# Provider-specific rate limiting
MAX_GITHUB_WORKERS = int(os.environ.get('MAX_GITHUB_WORKERS', '3'))      # GitHub API rate limit consideration
MAX_MICROSOFT_WORKERS = int(os.environ.get('MAX_MICROSOFT_WORKERS', '3'))   # Microsoft servers rate limit
MAX_GOOGLE_WORKERS = int(os.environ.get('MAX_GOOGLE_WORKERS', '4'))      # Google APIs rate limit

# Provider-specific configuration
PROVIDER_CONFIGS = {
    'github': {
        'max_workers': MAX_GITHUB_WORKERS,
        'base_url': 'https://api.github.com',
        'rate_limit_buffer': 100  # requests per hour buffer
    },
    'microsoft': {
        'max_workers': MAX_MICROSOFT_WORKERS,
        'base_url': 'https://www.microsoft.com',
        'retry_delay': 2.0  # seconds between retries
    },
    'google': {
        'max_workers': MAX_GOOGLE_WORKERS,
        'base_url': 'https://www.googleapis.com',
        'timeout_multiplier': 1.5  # longer timeouts for Google APIs
    }
}

# Logging configuration
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%H:%M:%S'

# File and directory constants
BUCKET_DIR = REPO_ROOT / 'bucket'
SCRIPTS_GLOB = 'update-*.py'
MANIFEST_EXTENSION = '.json'
MAX_MANIFEST_SIZE = 10 * 1024 * 1024  # 10MB max manifest file size

# Cache configuration
CACHE_EXPIRY_SECONDS = int(os.environ.get('CACHE_EXPIRY_SECONDS', '1800'))  # 30 minutes cache TTL

# Cache manifest versions in-memory during one orchestrator run to avoid
# repeated disk reads when printing summaries and composing commit messages.
MANIFEST_VERSION_CACHE: Dict[str, str] = {}

def run_git_command(args: List[str], cwd: Path = REPO_ROOT) -> Tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            encoding="utf-8",
            errors="replace"  # Handle encoding errors gracefully
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        logging.error(f"Git command failed: {e}")
        return 1, "", str(e)

def is_file_tracked(path: Path) -> bool:
    """Return True if the file is tracked by git."""
    rc, _, _ = run_git_command(["git", "ls-files", "--error-unmatch", str(path)])
    return rc == 0

def stage_bucket_changes() -> None:
    """Stage changes inside the bucket directory."""
    rc, out, err = run_git_command(["git", "add", "bucket"])
    if rc != 0:
        print(f"⚠️  git add failed: {err or out}")

def get_staged_bucket_changes() -> Tuple[List[str], List[str]]:
    """Return (added_apps, updated_apps) from staged changes under bucket/."""
    rc, out, err = run_git_command(["git", "diff", "--cached", "--name-status"])
    if rc != 0:
        print(f"⚠️  git diff --cached failed: {err or out}")
        return [], []

    added_apps: List[str] = []
    updated_apps: List[str] = []

    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        status, path = parts
        # Only consider manifests in bucket/
        if not path.startswith(f"{BUCKET_DIR.name}/") or not path.endswith(MANIFEST_EXTENSION):
            continue
        app_name = Path(path).stem
        if status.startswith("A"):  # Added
            added_apps.append(app_name)
        elif status.startswith("M") or status.startswith("R"):  # Modified or Renamed
            updated_apps.append(app_name)

    added_apps.sort()
    updated_apps.sort()
    return added_apps, updated_apps

def commit_with_message(message: str) -> bool:
    """Create a commit with the given message. Returns True if commit succeeded."""
    rc, out, err = run_git_command(["git", "commit", "-m", message])
    if rc != 0:
        # If there is nothing to commit, git returns non-zero; report and skip
        reason = err or out
        if "nothing to commit" in (reason.lower()):
            print("ℹ️  No changes staged to commit.")
        else:
            print(f"⚠️  git commit failed: {reason}")
        return False
    print(out or "✅ Commit created")
    return True

def push_changes() -> None:
    """Push committed changes to the remote."""
    rc, out, err = run_git_command(["git", "push"])
    if rc != 0:
        print(f"⚠️  git push failed: {err or out}")
    else:
        print(out or "⬆️  Pushed changes to remote")

def get_manifest_version(app_name: str) -> str:
    """Return version string from bucket/<app_name>.json if available, using cache."""
    # Return cached value if present
    if app_name in MANIFEST_VERSION_CACHE:
        return MANIFEST_VERSION_CACHE.get(app_name, "")

    manifest_path = BUCKET_DIR / f"{app_name}{MANIFEST_EXTENSION}"
    try:
        # Check file size before reading
        if manifest_path.exists() and manifest_path.stat().st_size > MAX_MANIFEST_SIZE:
            logging.warning(f"Manifest file too large: {manifest_path} ({manifest_path.stat().st_size} bytes)")
            MANIFEST_VERSION_CACHE[app_name] = ""
            return ""

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            version = str(manifest.get("version", "")).strip()
            MANIFEST_VERSION_CACHE[app_name] = version
            return version
    except Exception as e:
        logging.debug(f"Failed to read manifest {manifest_path}: {e}")
        # Cache miss with empty value to avoid reattempting in this run
        MANIFEST_VERSION_CACHE[app_name] = ""
        return ""

def list_untracked_manifests() -> List[Tuple[str, Path]]:
    """Return a list of (app_name, path) for untracked manifests under bucket/."""
    rc, out, err = run_git_command(["git", "ls-files", "--others", "--exclude-standard", str(BUCKET_DIR)])
    if rc != 0:
        print(f"⚠️  git ls-files failed: {err or out}")
        return []
    manifests: List[Tuple[str, Path]] = []
    for rel in out.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        if not rel.endswith(MANIFEST_EXTENSION):
            continue
        if not rel.startswith(f"{BUCKET_DIR.name}/"):
            continue
        p = REPO_ROOT / rel
        app_name = Path(rel).stem
        manifests.append((app_name, p))
    return manifests

def stage_and_commit_per_package(updated_results: List["UpdateResult"]) -> None:
    """Stage and commit changes per updated package manifest under bucket/."""
    for r in updated_results:
        # Derive package name from script name: update-<pkg>.py
        pkg = r.script_name.replace('update-', '').replace('.py', '')
        manifest_path = BUCKET_DIR / f"{pkg}{MANIFEST_EXTENSION}"

        if not manifest_path.exists():
            # If the script updated something else or the manifest name differs, skip gracefully
            continue

        # Stage only this manifest
        rc, out, err = run_git_command(["git", "add", str(manifest_path)])
        if rc != 0:
            print(f"⚠️  git add {manifest_path} failed: {err or out}")
            continue

        # Determine if there's a staged change and whether it's new or modified
        rc, ns_out, ns_err = run_git_command(["git", "diff", "--cached", "--name-status", "--", str(manifest_path)])
        if not ns_out.strip():
            print(f"ℹ️  No staged changes for {pkg}, skipping commit.")
            continue
        status_line = ns_out.strip().splitlines()[0]
        status_code = status_line.split("\t", 1)[0] if "\t" in status_line else ""
        new_file = status_code.startswith("A")

        # Read manifest version, if available
        version_str = get_manifest_version(pkg)

        if new_file:
            msg = f"{pkg}: Add version {version_str} (script: {r.script_name})" if version_str else f"{pkg}: Add manifest (script: {r.script_name})"
        else:
            msg = f"{pkg}: Update to version {version_str} (script: {r.script_name})" if version_str else f"{pkg}: Update manifest (script: {r.script_name})"
        commit_with_message(msg)

def discover_update_scripts() -> List[str]:
    """Automatically discover all update-*.py scripts in the scripts directory"""
    update_scripts = []

    # Find all update-*.py files
    for script_file in SCRIPTS_DIR.glob(SCRIPTS_GLOB):
        # Skip the update-all.py script itself and utility scripts
        if script_file.name not in ["update-all.py", "update-script-generator.py"] and not script_file.name.startswith("_"):
            update_scripts.append(script_file.name)

    # Sort for consistent ordering
    update_scripts.sort()

    print(f"🔍 Discovered {len(update_scripts)} update scripts:")
    for script in update_scripts:
        print(f"   • {script}")

    return update_scripts

class UpdateResult:
    """Class to store update results."""
    def __init__(self, script_name: str, success: bool, output: str, duration: float, updated: bool = False):
        self.script_name = script_name
        self.success = success
        self.output = output
        self.duration = duration
        self.updated = updated

def parse_script_output(output: str, script_name: str) -> tuple[bool, bool]:
    """Parse script output to determine update status."""
    # Prefer structured JSON result: search the last up to 10 non-empty lines for a JSON object
    structured_updated = None
    try:
        lines = [ln for ln in output.strip().splitlines() if ln.strip()]
        for ln in reversed(lines[-10:]):
            last = ln.strip()
            if last.startswith('{') and last.endswith('}'):
                import json as _json
                parsed = _json.loads(last)
                if isinstance(parsed, dict) and 'updated' in parsed:
                    structured_updated = bool(parsed.get('updated'))
                    # Prime version cache if provided
                    pkg = script_name.replace('update-', '').replace('.py', '')
                    v = parsed.get('version')
                    if isinstance(v, str) and v:
                        MANIFEST_VERSION_CACHE[pkg] = v
                    break
    except Exception:
        # Ignore JSON parsing issues; fall back to text heuristics
        pass

    if structured_updated is not None:
        updated = structured_updated
        no_update_needed = not updated
    else:
        updated = "update completed successfully" in output.lower() or "updated" in output.lower()
        no_update_needed = "no update needed" in output.lower() or "up to date" in output.lower()

    return updated, no_update_needed

def run_update_script(script_path: Path, timeout: int = 300) -> UpdateResult:
    """Run a single update script and return the result."""
    script_name = script_path.name
    start_time = time.time()

    try:
        logging.info(f"Running {script_name}...")
        print(f"🚀 Running {script_name}...")

        # Run the script
        # Change to the parent directory (where bucket/ is located) before running the script
        parent_dir = SCRIPTS_DIR.parent

        # Set environment to handle Unicode properly
        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=parent_dir,
            encoding='utf-8',
            errors='replace',
            env=env
        )

        duration = time.time() - start_time

        # Check if update was successful and if anything was updated
        output = result.stdout + result.stderr

        # Parse output for update status
        updated, no_update_needed = parse_script_output(output, script_name)

        if result.returncode == 0:
            if updated:
                print(f"✅ {script_name} - Updated successfully ({duration:.1f}s)")
                logging.info(f"{script_name} updated successfully")
            elif no_update_needed:
                print(f"ℹ️  {script_name} - No update needed ({duration:.1f}s)")
                logging.info(f"{script_name} no update needed")
            else:
                print(f"✅ {script_name} - Completed ({duration:.1f}s)")
                logging.info(f"{script_name} completed without updates")

            return UpdateResult(script_name, True, output, duration, updated)
        else:
            error_msg = result.stderr.strip() if result.stderr else 'Unknown error'
            stdout_msg = result.stdout.strip() if result.stdout else ''
            detailed_error = f"Exit code: {result.returncode}\nSTDERR: {error_msg}\nSTDOUT: {stdout_msg}"
            logging.error(f"{script_name} failed: {detailed_error}")
            print(f"❌ {script_name} - Failed ({duration:.1f}s)")
            print(f"   Error details: {detailed_error}")
            return UpdateResult(script_name, False, detailed_error, duration, False)

    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        logging.error(f"{script_name} timed out after {timeout}s")
        print(f"⏰ {script_name} - Timeout after {timeout}s")
        return UpdateResult(script_name, False, f"Script timed out after {timeout} seconds", duration, False)

    except Exception as e:
        duration = time.time() - start_time
        logging.error(f"{script_name} error: {e}")
        print(f"💥 {script_name} - Error: {e}")
        return UpdateResult(script_name, False, str(e), duration, False)

# New: retry wrapper for robustness
def run_update_script_with_retry(script_path: Path, timeout: int = 300, retries: int = 0) -> UpdateResult:
    attempt = 0
    last_result: UpdateResult = None  # type: ignore
    while attempt <= retries:
        result = run_update_script(script_path, timeout)
        if result.success:
            return result
        last_result = result
        attempt += 1
        if attempt <= retries:
            backoff = min(30, 2 ** attempt)
            print(f"🔁 Retrying {script_path.name} in {backoff}s (attempt {attempt}/{retries})")
            time.sleep(backoff)
    return last_result

def run_sequential(scripts: List[Path], timeout: int, delay: float = 0.0, retries: int = 0) -> List[UpdateResult]:
    """Run update scripts sequentially.

    Args:
        scripts: List of script paths to run
        timeout: Timeout per script in seconds
        delay: Optional delay (in seconds) between scripts to avoid overwhelming APIs
        retries: Number of retry attempts per script (default: 0)
    """
    results = []

    for script_path in scripts:
        result = run_update_script_with_retry(script_path, timeout, retries)
        results.append(result)

        # Optional delay between scripts
        if delay and delay > 0:
            time.sleep(delay)

    return results

def run_parallel(scripts: List[Path], timeout: int, max_workers: int, *, github_workers: int = 3, microsoft_workers: int = 3, google_workers: int = 4, retries: int = 0) -> List[UpdateResult]:
    """Run update scripts in parallel with provider-aware throttling."""
    results = []

    # Helper: classify provider based on script content
    def classify_provider(p: Path) -> str:
        try:
            with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(4000)
                if ('github.com' in content) or ('api.github.com' in content):
                    return 'github'
                if ('learn.microsoft.com' in content) or ('go.microsoft.com' in content) or ('download.microsoft.com' in content) or ('visualstudio.microsoft.com' in content):
                    return 'microsoft'
                if ('googleapis.com' in content) or ('storage.googleapis.com' in content) or ('dl.google.com' in content) or ('cloudfront.net' in content):
                    return 'google'
                return 'other'
        except Exception:
            return 'other'

    # Cap workers to the number of scripts to avoid oversubscription
    max_workers = max(1, min(max_workers, len(scripts)))

    # Compute provider classification and throttling semaphores
    prov_map: Dict[Path, str] = {p: classify_provider(p) for p in scripts}
    counts = {
        'github': sum(1 for v in prov_map.values() if v == 'github'),
        'microsoft': sum(1 for v in prov_map.values() if v == 'microsoft'),
        'google': sum(1 for v in prov_map.values() if v == 'google'),
        'other': sum(1 for v in prov_map.values() if v == 'other'),
    }
    sems = {
        'github': threading.BoundedSemaphore(value=max(1, min(github_workers, max_workers))),
        'microsoft': threading.BoundedSemaphore(value=max(1, min(microsoft_workers, max_workers))),
        'google': threading.BoundedSemaphore(value=max(1, min(google_workers, max_workers))),
        'other': threading.BoundedSemaphore(value=max(1, max_workers)),
    }
    print(f"🔗 Provider-aware throttling: GitHub={counts['github']} (max {github_workers}), Microsoft={counts['microsoft']} (max {microsoft_workers}), Google={counts['google']} (max {google_workers}), Other={counts['other']}")

    def _task(script_path: Path, timeout: int) -> UpdateResult:
        prov = prov_map.get(script_path, 'other')
        with sems.get(prov, sems['other']):
            return run_update_script_with_retry(script_path, timeout, retries)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all scripts with throttling wrapper
        future_to_script = {
            executor.submit(_task, script_path, timeout): script_path
            for script_path in scripts
        }

        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_script):
            script_path = future_to_script[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                print(f"💥 {script_path.name} - Unexpected error: {e}")
                results.append(UpdateResult(script_path.name, False, str(e), 0, False))

    # Sort results by script name for consistent output
    results.sort(key=lambda x: x.script_name)
    return results

def print_summary(results: List[UpdateResult], total_duration: float):
    """Print a summary of all update results."""
    print("\n" + "="*80)

def write_json_summary(results: List[UpdateResult], total_duration: float, args, mode_label: str) -> None:
    try:
        if not args.json_summary:
            return
        summary_path = Path(args.json_summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "started_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "mode": mode_label,
            "timeout": args.timeout,
            "workers": args.workers if args.parallel else 1,
            "provider_workers": {
                "github": args.github_workers,
                "microsoft": args.microsoft_workers,
                "google": args.google_workers,
            },
            "total_duration_seconds": round(total_duration, 3),
            "results": [],
            "counts": {
                "total": len(results),
                "successful": len([r for r in results if r.success]),
                "failed": len([r for r in results if not r.success]),
                "updated": len([r for r in results if r.updated]),
                "no_updates": len([r for r in results if r.success and not r.updated]),
            },
        }

        for r in results:
            pkg = r.script_name.replace('update-', '').replace('.py', '')
            version = get_manifest_version(pkg)
            data["results"].append({
                "script": r.script_name,
                "package": pkg,
                "success": r.success,
                "updated": r.updated,
                "duration_seconds": round(r.duration, 3),
                "version": version or "",
            })

        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"🧾 JSON summary written to: {summary_path}")
    except Exception as e:
        print(f"⚠️  Failed to write JSON summary: {e}")
    print("📊 UPDATE SUMMARY")
    print("="*80)

    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    updated = [r for r in results if r.updated]

    print(f"📈 Total Scripts: {len(results)}")
    print(f"✅ Successful: {len(successful)}")
    print(f"❌ Failed: {len(failed)}")
    print(f"🔄 Updated: {len(updated)}")
    print(f"⏱️  Total Duration: {total_duration:.1f}s")

    if updated:
        print(f"\n🎉 PACKAGES UPDATED:")
        for result in updated:
            package_name = result.script_name.replace('update-', '').replace('.py', '')
            version = get_manifest_version(package_name)
            if version:
                print(f"   • {package_name}: Update to version {version} ({result.duration:.1f}s)")
            else:
                print(f"   • {package_name} ({result.duration:.1f}s)")

    if failed:
        print(f"\n❌ FAILED SCRIPTS:")
        for result in failed:
            print(f"   • {result.script_name} ({result.duration:.1f}s)")
            # Show first few lines of error output
            error_lines = result.output.strip().split('\n')[:3]
            for line in error_lines:
                if line.strip():
                    print(f"     {line.strip()}")

    no_updates = [r for r in successful if not r.updated]
    if no_updates:
        print(f"\nℹ️  NO UPDATES NEEDED:")
        for result in no_updates:
            package_name = result.script_name.replace('update-', '').replace('.py', '')
            version = get_manifest_version(package_name)
            if version:
                print(f"   • {package_name} (version {version})")
            else:
                print(f"   • {package_name}")

    print("\n" + "="*80)

def check_dependencies():
    """Check if required dependencies are installed."""
    missing_deps = []
    optional_deps = []

    # Check core dependencies
    try:
        import requests
    except ImportError:
        missing_deps.append("requests")

    try:
        import packaging
    except ImportError:
        missing_deps.append("packaging")

    # Check optional dependencies
    try:
        import bs4
    except ImportError:
        optional_deps.append("beautifulsoup4")

    if missing_deps:
        print(f"❌ Missing required dependencies: {', '.join(missing_deps)}")
        print("Please install required packages:")
        print(f"pip install {' '.join(missing_deps)}")
        return False

    if optional_deps:
        print(f"⚠️  Warning: Optional dependencies not found: {', '.join(optional_deps)}")
        print("Some features may be limited. Install with:")
        print(f"pip install {' '.join(optional_deps)}")

    return True

def setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Configure logging based on verbosity settings."""
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    # Override with environment variable if set
    if LOG_LEVEL != 'INFO':
        level = getattr(logging, LOG_LEVEL, logging.INFO)

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT
    )

def main():
    """Main function to orchestrate all update scripts."""
    parser = argparse.ArgumentParser(
        description="Run all Scoop bucket update scripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/update-all.py                    # Run all scripts in parallel
  python scripts/update-all.py --sequential       # Run scripts sequentially
  python scripts/update-all.py --workers 8        # Use 8 parallel workers
  python scripts/update-all.py --scripts corecycler esptool  # Run specific scripts
  python scripts/update-all.py --fast --retry 2   # Fast mode with retries
        """
    )

    # Execution mode
    execution_group = parser.add_argument_group('Execution Mode')
    execution_group.add_argument("--parallel", "-p", action="store_true", default=True,
                       help="Run scripts in parallel (default)")
    execution_group.add_argument("--sequential", action="store_true",
                       help="Force sequential execution")
    execution_group.add_argument("--fast", "-f", action="store_true",
                       help="Enable fast mode with optimized worker count")

    # Performance tuning
    performance_group = parser.add_argument_group('Performance')
    performance_group.add_argument("--workers", "-w", type=int, default=DEFAULT_WORKERS,
                       help=f"Number of parallel workers (default: {DEFAULT_WORKERS})")
    performance_group.add_argument("--timeout", "-t", type=int, default=DEFAULT_TIMEOUT,
                       help=f"Timeout per script in seconds (default: {DEFAULT_TIMEOUT})")
    performance_group.add_argument("--delay", "-D", type=float, default=0.0,
                       help="Delay (seconds) between scripts in sequential mode")

    # Provider-specific throttling
    throttling_group = parser.add_argument_group('Provider Throttling')
    throttling_group.add_argument("--github-workers", type=int, default=MAX_GITHUB_WORKERS,
                       help=f"Max concurrent GitHub-related scripts (default: {MAX_GITHUB_WORKERS})")
    throttling_group.add_argument("--microsoft-workers", type=int, default=MAX_MICROSOFT_WORKERS,
                       help=f"Max concurrent Microsoft-related scripts (default: {MAX_MICROSOFT_WORKERS})")
    throttling_group.add_argument("--google-workers", type=int, default=MAX_GOOGLE_WORKERS,
                       help=f"Max concurrent Google-related scripts (default: {MAX_GOOGLE_WORKERS})")
    parser.add_argument("--scripts", "-s", nargs="+",
                       help="Run only specific scripts (e.g., corecycler esptool)")
    parser.add_argument("--dry-run", "-d", action="store_true",
                       help="Show what would be run without executing")
    parser.add_argument("--skip-git", action="store_true",
                       help="Skip git add/commit/push after updates")
    parser.add_argument("--git-per-package", action="store_true",
                       help="Stage & commit each updated manifest individually with its own message")
    parser.add_argument("--git-aggregate", action="store_true",
                       help="Stage & commit all changes in aggregate groups (overrides per-package default)")
    parser.add_argument("--structured-output", action="store_true",
                       help="Prefer structured JSON output from update scripts (falls back to text heuristics)")
    parser.add_argument("--http-cache", action="store_true",
                       help="Enable short-lived HTTP response caching for update scripts during this run")
    parser.add_argument("--http-cache-ttl", type=int, default=1800,
                       help="HTTP cache TTL in seconds when --http-cache is enabled (default: 1800)")
    parser.add_argument("--retry", type=int, default=0,
                       help="Number of retry attempts per script on failure (default: 0)")
    parser.add_argument("--json-summary", type=Path,
                       help="Write machine-readable JSON summary to the given file path")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose logging")
    parser.add_argument("--quiet", "-q", action="store_true",
                       help="Reduce logging output")

    args = parser.parse_args()

    # Configure logging
    setup_logging(args.verbose, args.quiet)

    # Check dependencies
    if not check_dependencies():
        sys.exit(1)

    # Discover available update scripts
    available_scripts = discover_update_scripts()

    # Determine which scripts to run
    if args.scripts:
        # Validate provided script names
        available_scripts_set = set(available_scripts)
        selected_scripts = []

        for script in args.scripts:
            if not script.startswith('update-') or not script.endswith('.py'):
                script = f'update-{script}.py'

            if script in available_scripts_set:
                selected_scripts.append(script)
            else:
                print(f"❌ Unknown script: {script}")
                print(f"Available scripts: {', '.join(sorted(available_scripts_set))}")
                sys.exit(1)

        scripts_to_run = selected_scripts
    else:
        scripts_to_run = available_scripts

    # Verify all script files exist
    script_paths = []
    for script_name in scripts_to_run:
        script_path = SCRIPTS_DIR / script_name
        if script_path.exists():
            script_paths.append(script_path)
        else:
            print(f"⚠️  Script not found: {script_path}")

    if not script_paths:
        print("❌ No valid script files found")
        sys.exit(1)

    # Show what will be run
    logging.info("Starting Scoop Bucket Update Orchestrator")
    print("🔧 Scoop Bucket Update Orchestrator")
    print(f"📅 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📂 Scripts directory: {SCRIPTS_DIR}")

    # Resolve mode: if --sequential is set, override parallel
    if args.sequential:
        args.parallel = False
        logging.info("Running in sequential mode")
    else:
        args.parallel = True
        logging.info("Running in parallel mode")

    print(f"🎯 Mode: {'Parallel' if args.parallel else 'Sequential'}")
    if args.parallel:
        # Clamp workers to number of scripts
        args.workers = max(1, min(args.workers, len(script_paths)))
        print(f"👥 Workers: {args.workers}")
        logging.info(f"Using {args.workers} parallel workers")
    else:
        print(f"⏳ Sequential delay: {args.delay:.1f}s")
        if args.delay > 0:
            logging.info(f"Sequential delay set to {args.delay}s")

    print(f"⏱️  Timeout: {args.timeout}s per script")
    print(f"📋 Scripts to run ({len(script_paths)}):")

    for script_path in script_paths:
        package_name = script_path.name.replace('update-', '').replace('.py', '')
        print(f"   • {package_name}")
        logging.debug(f"Will run script for package: {package_name}")

    if args.dry_run:
        print("\n🔍 DRY RUN - No scripts will be executed")
        return

    print("\n" + "="*80)

    # Run the scripts
    start_time = time.time()

    # Propagate HTTP cache settings to child processes
    if args.http_cache:
        os.environ['AUTOMATION_HTTP_CACHE'] = '1'
        os.environ['AUTOMATION_HTTP_CACHE_TTL'] = str(args.http_cache_ttl)

    # If fast mode is enabled, force parallel with an optimized worker count
    if args.fast:
        args.parallel = True
        # Recommend worker count based on CPU and script count (network-bound tasks benefit from moderate concurrency)
        recommended_workers = min(6, max(3, (os.cpu_count() or 4)))
        args.workers = min(recommended_workers, len(script_paths))
        print(f"⚡ Fast mode enabled: workers set to {args.workers}")

    if args.parallel:
        results = run_parallel(script_paths, args.timeout, args.workers, github_workers=args.github_workers, microsoft_workers=args.microsoft_workers, google_workers=args.google_workers, retries=args.retry)
    else:
        results = run_sequential(script_paths, args.timeout, args.delay, retries=args.retry)

    total_duration = time.time() - start_time

    # Print summary
    print_summary(results, total_duration)
    # Optional JSON summary output
    write_json_summary(results, total_duration, args, 'Parallel' if args.parallel else 'Sequential')

    # Exit with appropriate code
    failed_count = len([r for r in results if not r.success])
    if failed_count > 0:
        print(f"\n⚠️  {failed_count} script(s) failed")
        sys.exit(1)
    else:
        # Optionally perform git add/commit/push
        if not args.skip_git:
            print("\n" + "-"*80)
            print("🧩 Git integration: staging and committing changes...")
            try:
                use_per_package = args.git_per_package or not args.git_aggregate
                if use_per_package:
                    # Per-package staging/commit using the results
                    updated_results = [r for r in results if r.updated]
                    if not updated_results:
                        print("ℹ️  No updated packages to commit.")
                    else:
                        stage_and_commit_per_package(updated_results)
                        # Also handle newly added manifests (e.g., from manifest-generator)
                        new_manifests = list_untracked_manifests()
                        for app_name, path in new_manifests:
                            rc, out, err = run_git_command(["git", "add", str(path)])
                            if rc != 0:
                                print(f"⚠️  git add {path} failed: {err or out}")
                                continue
                            version_str = get_manifest_version(app_name)
                            msg = f"{app_name}: Add version {version_str}" if version_str else f"{app_name}: Add manifest"
                            commit_with_message(msg)
                        push_changes()
                else:
                    # Aggregate commit: stage entire bucket and commit added/updated groups
                    stage_bucket_changes()
                    added_apps, updated_apps = get_staged_bucket_changes()

                    if not added_apps and not updated_apps:
                        print("ℹ️  No staged changes found under bucket/ to commit.")
                    else:
                        if updated_apps:
                            # Include versions in grouped commit with count
                            updated_with_versions = []
                            for app in updated_apps:
                                v = get_manifest_version(app)
                                updated_with_versions.append(f"{app} {v}" if v else app)
                            msg = f"updated ({len(updated_with_versions)}): " + ", ".join(updated_with_versions)
                            print(f"📝 Committing: {msg}")
                            commit_with_message(msg)
                        if added_apps:
                            added_with_versions = []
                            for app in added_apps:
                                v = get_manifest_version(app)
                                added_with_versions.append(f"{app} {v}" if v else app)
                            msg = f"added ({len(added_with_versions)}): " + ", ".join(added_with_versions)
                            print(f"📝 Committing: {msg}")
                            commit_with_message(msg)
                        push_changes()
            except Exception as e:
                print(f"⚠️  Git integration encountered an error: {e}")

        print(f"\n🎉 All scripts completed successfully!")
        sys.exit(0)

if __name__ == "__main__":
    main()
