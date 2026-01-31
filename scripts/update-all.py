#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Scoop Bucket Update Orchestrator
Runs all update scripts for the scoop-alts bucket and provides a summary report.
"""
from __future__ import annotations

import argparse
import codecs
import concurrent.futures
import importlib.util
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Any

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "detach"):
            sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        if hasattr(sys.stderr, "detach"):
            sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())
    except Exception:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")

try:
    import requests
except ImportError:
    requests = None  # Handled in check_dependencies

# Configuration
SCRIPTS_DIR = Path(__file__).parent
sys.path.append(str(SCRIPTS_DIR))
REPO_ROOT = SCRIPTS_DIR.parent

# Performance and Concurrency Constants
DEFAULT_TIMEOUT = int(os.environ.get('SCOOP_UPDATE_TIMEOUT', '120'))
DEFAULT_WORKERS = int(os.environ.get('SCOOP_UPDATE_WORKERS', '6'))
DEFAULT_RETRY_ATTEMPTS = int(os.environ.get('SCOOP_RETRY_ATTEMPTS', '0'))

# Provider-specific rate limiting
MAX_GITHUB_WORKERS = int(os.environ.get('MAX_GITHUB_WORKERS', '3'))
MAX_MICROSOFT_WORKERS = int(os.environ.get('MAX_MICROSOFT_WORKERS', '3'))
MAX_GOOGLE_WORKERS = int(os.environ.get('MAX_GOOGLE_WORKERS', '4'))

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
CACHE_EXPIRY_SECONDS = int(os.environ.get('CACHE_EXPIRY_SECONDS', '1800'))

# Provider Domain Constants
MICROSOFT_DOMAINS = frozenset({
    'learn.microsoft.com', 'go.microsoft.com', 
    'download.microsoft.com', 'visualstudio.microsoft.com'
})
GOOGLE_DOMAINS = frozenset({
    'googleapis.com', 'storage.googleapis.com', 
    'dl.google.com', 'cloudfront.net'
})

# Cache manifest versions in-memory
MANIFEST_VERSION_CACHE: Dict[str, str] = {}
PREFER_STRUCTURED_OUTPUT = False

@dataclass
class UpdateResult:
    """Class to store update results."""
    script_name: str
    success: bool
    output: str
    duration: float
    updated: bool = False

def run_git_command(args: List[str], cwd: Path = REPO_ROOT) -> Tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            encoding="utf-8",
            errors="replace"
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        logging.error(f"Git command failed: {e}")
        return 1, "", str(e)

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

    # Parse lines and filter for bucket manifests
    added, updated = [], []
    prefix = f"{BUCKET_DIR.name}/"
    
    for line in out.splitlines():
        if (parts := line.strip().split("\t", 1)) and len(parts) == 2:
            status, path = parts
            if path.startswith(prefix) and path.endswith(MANIFEST_EXTENSION):
                stem = Path(path).stem
                if status.startswith("A"):
                    added.append(stem)
                elif status.startswith(("M", "R")):
                    updated.append(stem)

    return sorted(added), sorted(updated)

def commit_with_message(message: str) -> bool:
    """Create a commit with the given message. Returns True if commit succeeded."""
    rc, out, err = run_git_command(["git", "commit", "-m", message])
    if rc != 0:
        reason = err or out
        if "nothing to commit" in reason.lower():
            print("ℹ️  No changes staged to commit.")
        else:
            print(f"⚠️  git commit failed: {reason}")
        return False
    print(out or "✅ Commit created")
    return True

def push_changes() -> None:
    """Push committed changes to the remote (env overrides supported)."""
    remote = os.environ.get("SCOOP_GIT_REMOTE", "origin")
    branch = os.environ.get("SCOOP_GIT_BRANCH")
    if os.environ.get("SCOOP_GIT_DRY_RUN") == "1":
        print(f"ℹ️  Dry-run: would push to {remote}{' ' + branch if branch else ''}")
        return
    args = ["git", "push", remote] + ([branch] if branch else [])
    rc, out, err = run_git_command(args)
    if rc != 0:
        print(f"⚠️  git push failed: {err or out}")
    else:
        print(out or "⬆️  Pushed changes to remote")

def get_manifest_version(app_name: str) -> str:
    """Return version string from bucket/<app_name>.json if available, using cache."""
    if app_name in MANIFEST_VERSION_CACHE:
        return MANIFEST_VERSION_CACHE.get(app_name, "")

    manifest_path = BUCKET_DIR / f"{app_name}{MANIFEST_EXTENSION}"
    try:
        st = manifest_path.stat()
        if st.st_size > MAX_MANIFEST_SIZE:
            logging.warning(f"Manifest file too large: {manifest_path} ({st.st_size} bytes)")
            MANIFEST_VERSION_CACHE[app_name] = ""
            return ""

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            version = str(manifest.get("version", "")).strip()
            MANIFEST_VERSION_CACHE[app_name] = version
            return version
    except FileNotFoundError:
        MANIFEST_VERSION_CACHE[app_name] = ""
        return ""
    except Exception as e:
        logging.debug(f"Failed to read manifest {manifest_path}: {e}")
        MANIFEST_VERSION_CACHE[app_name] = ""
        return ""

def list_untracked_manifests() -> List[Tuple[str, Path]]:
    """Return a list of (app_name, path) for untracked manifests under bucket/."""
    rc, out, err = run_git_command(["git", "ls-files", "--others", "--exclude-standard", str(BUCKET_DIR)])
    if rc != 0:
        print(f"⚠️  git ls-files failed: {err or out}")
        return []
    
    return [
        (Path(rel).stem, REPO_ROOT / rel)
        for rel in out.splitlines()
        if rel.strip() 
        and rel.endswith(MANIFEST_EXTENSION) 
        and rel.startswith(f"{BUCKET_DIR.name}/")
    ]

def stage_and_commit_per_package(updated_results: List[UpdateResult]) -> None:
    """Stage and commit changes per updated package manifest under bucket/."""
    for r in updated_results:
        pkg = r.script_name.replace('update-', '').replace('.py', '')
        manifest_path = BUCKET_DIR / f"{pkg}{MANIFEST_EXTENSION}"

        if not manifest_path.exists():
            continue

        rc, out, err = run_git_command(["git", "add", str(manifest_path)])
        if rc != 0:
            print(f"⚠️  git add {manifest_path} failed: {err or out}")
            continue

        rc, ns_out, _ = run_git_command(["git", "diff", "--cached", "--name-status", "--", str(manifest_path)])
        if not ns_out.strip():
            print(f"ℹ️  No staged changes for {pkg}, skipping commit.")
            continue
            
        status_line = ns_out.strip().splitlines()[0]
        status_code = status_line.split("\t", 1)[0] if "\t" in status_line else ""
        new_file = status_code.startswith("A")

        version_str = get_manifest_version(pkg)
        action = "Add" if new_file else "Update to"
        msg = f"{pkg}: {action} version {version_str} (script: {r.script_name})" if version_str else f"{pkg}: {action} manifest (script: {r.script_name})"
        commit_with_message(msg)

def discover_update_scripts() -> List[str]:
    """Automatically discover all update-*.py scripts in the scripts directory"""
    scripts = sorted(
        f.name for f in SCRIPTS_DIR.glob(SCRIPTS_GLOB)
        if f.name not in {"update-all.py", "update-script-generator.py"} 
        and not f.name.startswith("_")
    )
    
    print(f"🔍 Discovered {len(scripts)} update scripts:")
    for script in scripts:
        print(f"   • {script}")

    return scripts

def parse_script_output(output: str, script_name: str) -> Tuple[bool, bool]:
    """Parse script output to determine update status."""
    structured_updated = None
    
    # Fast regex search for JSON result
    # Look for {"updated": true/false...} pattern
    if match := re.search(r'\{.*"updated"\s*:\s*(true|false|null).*\}', output, re.DOTALL):
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict) and 'updated' in parsed:
                structured_updated = bool(parsed.get('updated'))
                pkg = script_name.replace('update-', '').replace('.py', '')
                if (v := parsed.get('version')) and isinstance(v, str):
                    MANIFEST_VERSION_CACHE[pkg] = v
        except json.JSONDecodeError:
            pass

    if structured_updated is None:
        lines = [ln.strip() for ln in output.strip().splitlines() if ln.strip()]
        
        # Fallback: search the last up to 10 non-empty lines for JSON-like structure
        for ln in reversed(lines[-10:]):
            if ln.startswith('{') and ln.endswith('}'):
                try:
                    parsed = json.loads(ln)
                    if isinstance(parsed, dict) and 'updated' in parsed:
                        structured_updated = bool(parsed.get('updated'))
                        pkg = script_name.replace('update-', '').replace('.py', '')
                        if (v := parsed.get('version')) and isinstance(v, str):
                            MANIFEST_VERSION_CACHE[pkg] = v
                        break
                except json.JSONDecodeError:
                    continue

    if structured_updated is not None:
        return structured_updated, not structured_updated
        
    if PREFER_STRUCTURED_OUTPUT:
        return False, False
        
    lower = output.lower()
    updated = "update completed successfully" in lower or "updated" in lower
    no_update_needed = "no update needed" in lower or "up to date" in lower

    return updated, no_update_needed

def run_update_script(script_path: Path, timeout: int = 300) -> UpdateResult:
    """Run a single update script and return the result."""
    script_name = script_path.name
    start_time = time.time()

    try:
        logging.info(f"Running {script_name}...")
        print(f"🚀 Running {script_name}...")

        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=SCRIPTS_DIR.parent,
            encoding='utf-8',
            errors='replace',
            env=env
        )

        duration = time.time() - start_time
        output = result.stdout + result.stderr
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

def run_update_script_with_retry(script_path: Path, timeout: int = 300, retries: int = 0) -> UpdateResult:
    attempt = 0
    last_result: Optional[UpdateResult] = None
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
    # last_result is guaranteed to be set because loop runs at least once (0 <= 0)
    return last_result # type: ignore

def classify_provider(path: Path, provider_map: Dict[str, str]) -> str:
    """Classify the provider for a given script path."""
    name = path.name
    pkg = name.replace('update-', '').replace('.py', '')
    
    if mapped := (provider_map.get(name) or provider_map.get(pkg)):
        return mapped

    try:
        # Read only first 4KB for classification to minimize I/O
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(4000)
        
        if 'github.com' in content or 'api.github.com' in content:
            return 'github'
        if any(x in content for x in MICROSOFT_DOMAINS):
            return 'microsoft'
        if any(x in content for x in GOOGLE_DOMAINS):
            return 'google'
    except Exception:
        pass
        
    return 'other'

def run_sequential(scripts: List[Path], timeout: int, delay: float = 0.0, retries: int = 0, *, fail_fast: bool = False, max_fail: int = 0) -> List[UpdateResult]:
    results = []
    failures = 0
    for script_path in scripts:
        result = run_update_script_with_retry(script_path, timeout, retries)
        results.append(result)
        if not result.success:
            failures += 1
            if fail_fast or (max_fail and failures >= max_fail):
                print("⛔ Stopping sequential execution due to failures")
                break
        if delay > 0:
            time.sleep(delay)
    return results

def run_parallel(scripts: List[Path], timeout: int, max_workers: int, *, github_workers: int = 3, microsoft_workers: int = 3, google_workers: int = 4, retries: int = 0, circuit_threshold: int = 3, circuit_sleep: float = 5.0) -> List[UpdateResult]:
    results = []
    
    # Load provider map
    provider_map: Dict[str, str] = {}
    try:
        map_path = SCRIPTS_DIR / 'providers.json'
        if map_path.exists():
            with open(map_path, 'r', encoding='utf-8') as f:
                provider_map = json.load(f)
    except Exception:
        pass

    # Cap workers
    max_workers = max(1, min(max_workers, len(scripts)))

    # Classify providers
    prov_map = {p: classify_provider(p, provider_map) for p in scripts}
    
    counts = Counter(prov_map.values())
    for k in ['github', 'microsoft', 'google', 'other']:
        counts.setdefault(k, 0)
    
    sems = {
        'github': threading.BoundedSemaphore(max(1, min(github_workers, max_workers))),
        'microsoft': threading.BoundedSemaphore(max(1, min(microsoft_workers, max_workers))),
        'google': threading.BoundedSemaphore(max(1, min(google_workers, max_workers))),
        'other': threading.BoundedSemaphore(max(1, max_workers)),
    }
    
    print(f"🔗 Provider-aware throttling: GitHub={counts['github']} (max {github_workers}), Microsoft={counts['microsoft']} (max {microsoft_workers}), Google={counts['google']} (max {google_workers}), Other={counts['other']}")

    prov_paused_until: Dict[str, float] = {k: 0.0 for k in ['github', 'microsoft', 'google', 'other']}
    prov_failures: Dict[str, int] = {k: 0 for k in ['github', 'microsoft', 'google', 'other']}
    lock = threading.Lock()

    def _task(script_path: Path, timeout: int) -> UpdateResult:
        prov = prov_map.get(script_path, 'other')
        now = time.time()
        if (until := prov_paused_until.get(prov, 0.0)) and now < until:
            time.sleep(min(circuit_sleep, until - now))
            
        with sems.get(prov, sems['other']):
            return run_update_script_with_retry(script_path, timeout, retries)

    # Check for Rich
    try:
        from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
        rich_available = True
    except ImportError:
        rich_available = False

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_script = {
            executor.submit(_task, script_path, timeout): script_path
            for script_path in scripts
        }

        if rich_available:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
            ) as progress:
                task_id = progress.add_task(f"[cyan]Running {len(scripts)} scripts...", total=len(scripts))
                
                for future in concurrent.futures.as_completed(future_to_script):
                    script_path = future_to_script[future]
                    try:
                        result = future.result()
                        results.append(result)
                        progress.advance(task_id)
                        
                        if not result.success:
                            prov = prov_map.get(script_path, 'other')
                            with lock:
                                prov_failures[prov] = prov_failures.get(prov, 0) + 1
                                if circuit_threshold > 0 and prov_failures[prov] >= circuit_threshold:
                                    prov_paused_until[prov] = time.time() + circuit_sleep
                                    prov_failures[prov] = 0
                                    progress.console.print(f"[yellow]⏸️  Pausing {prov} tasks for {circuit_sleep:.1f}s due to failures[/yellow]")
                    except Exception as e:
                        progress.console.print(f"[red]💥 {script_path.name} - Unexpected error: {e}[/red]")
                        results.append(UpdateResult(script_path.name, False, str(e), 0, False))
                        progress.advance(task_id)
        else:
            for future in concurrent.futures.as_completed(future_to_script):
                script_path = future_to_script[future]
                try:
                    result = future.result()
                    results.append(result)
                    if not result.success:
                        prov = prov_map.get(script_path, 'other')
                        with lock:
                            prov_failures[prov] = prov_failures.get(prov, 0) + 1
                            if circuit_threshold > 0 and prov_failures[prov] >= circuit_threshold:
                                prov_paused_until[prov] = time.time() + circuit_sleep
                                prov_failures[prov] = 0
                                print(f"⏸️  Pausing {prov} tasks for {circuit_sleep:.1f}s due to failures")
                except Exception as e:
                    print(f"💥 {script_path.name} - Unexpected error: {e}")
                    results.append(UpdateResult(script_path.name, False, str(e), 0, False))

    results.sort(key=lambda x: x.script_name)
    return results

def print_summary(results: List[UpdateResult], total_duration: float):
    print("\n" + "="*80)
    print("📊 UPDATE SUMMARY")
    print("="*80)
    
    successful, failed, updated = [], [], []
    for r in results:
        (successful if r.success else failed).append(r)
        if r.updated:
            updated.append(r)
    
    print(f"📈 Total Scripts: {len(results)}")
    print(f"✅ Successful: {len(successful)}")
    print(f"❌ Failed: {len(failed)}")
    print(f"🔄 Updated: {len(updated)}")
    print(f"⏱️  Total Duration: {total_duration:.1f}s")
    
    if updated:
        print(f"\n🎉 PACKAGES UPDATED:")
        for result in updated:
            pkg = result.script_name.replace('update-', '').replace('.py', '')
            version = get_manifest_version(pkg)
            if version:
                print(f"   • {pkg}: Update to version {version} ({result.duration:.1f}s)")
            else:
                print(f"   • {pkg} ({result.duration:.1f}s)")
                
    if failed:
        print(f"\n❌ FAILED SCRIPTS:")
        for result in failed:
            print(f"   • {result.script_name} ({result.duration:.1f}s)")
            for line in result.output.strip().splitlines()[:3]:
                if line.strip():
                    print(f"     {line.strip()}")
                    
    if no_updates := [r for r in successful if not r.updated]:
        print(f"\nℹ️  NO UPDATES NEEDED:")
        for result in no_updates:
            pkg = result.script_name.replace('update-', '').replace('.py', '')
            if version := get_manifest_version(pkg):
                print(f"   • {pkg} (version {version})")
            else:
                print(f"   • {pkg}")
    print("\n" + "="*80)

def write_json_summary(results: List[UpdateResult], total_duration: float, args, mode_label: str) -> None:
    try:
        if not args.json_summary:
            return
        summary_path = Path(args.json_summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)

        succ = fail = upd = no_upd = 0
        for r in results:
            if r.success:
                succ += 1
                if r.updated:
                    upd += 1
                else:
                    no_upd += 1
            else:
                fail += 1

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
                "successful": succ,
                "failed": fail,
                "updated": upd,
                "no_updates": no_upd,
            },
        }

        for r in results:
            pkg = r.script_name.replace('update-', '').replace('.py', '')
            data["results"].append({
                "script": r.script_name,
                "package": pkg,
                "success": r.success,
                "updated": r.updated,
                "duration_seconds": round(r.duration, 3),
                "version": get_manifest_version(pkg) or "",
                "error_preview": ("\n".join(r.output.strip().splitlines()[:3]) if not r.success else ""),
            })

        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"🧾 JSON summary written to: {summary_path}")
    except Exception as e:
        print(f"⚠️  Failed to write JSON summary: {e}")

def write_md_summary(results: List[UpdateResult], total_duration: float, args, mode_label: str) -> None:
    try:
        if not getattr(args, 'md_summary', None):
            return
        out_path = Path(args.md_summary)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        counts = {
            "total": len(results),
            "success": len([r for r in results if r.success]),
            "failed": len([r for r in results if not r.success]),
            "updated": len([r for r in results if r.updated])
        }
        
        lines = [
            "# Update Health Dashboard", "",
            f"- Mode: {mode_label}",
            f"- Total: {counts['total']}",
            f"- Successful: {counts['success']}",
            f"- Failed: {counts['failed']}",
            f"- Updated: {counts['updated']}", "",
            "| Package | Version | Success | Updated | Duration (s) |",
            "|---|---|---|---|---|",
        ]
        
        for r in results:
            pkg = r.script_name.replace('update-', '').replace('.py', '')
            version = get_manifest_version(pkg) or ""
            lines.append(f"| {pkg} | {version} | {str(r.success)} | {str(r.updated)} | {round(r.duration, 3)} |")
            
        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"🧾 Markdown summary written to: {out_path}")
    except Exception as e:
        print(f"⚠️  Failed to write Markdown summary: {e}")

def send_webhook_if_configured(args) -> None:
    try:
        if not args.webhook_url or not args.json_summary:
            return
        
        try:
            with open(args.json_summary, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except Exception as e:
            print(f"⚠️  Webhook skipped: cannot read summary file: {e}")
            return
            
        headers = {'Content-Type': 'application/json'}
        if args.webhook_header_name and args.webhook_header_value:
            headers[args.webhook_header_name] = args.webhook_header_value
            
        # Try to import format_webhook_body from summary_utils
        try:
            from summary_utils import format_webhook_body
        except ImportError:
            format_webhook_body = lambda p, t: p

        body = format_webhook_body(payload, getattr(args, 'webhook_type', 'generic'))
        
        if not requests:
            print("⚠️  Webhook skipped: requests library not installed")
            return

        for delay in [0.5, 1.0, 2.0]:
            try:
                resp = requests.post(args.webhook_url, json=body, headers=headers, timeout=15)
                if 200 <= resp.status_code < 300:
                    print(f"📣 Webhook delivered: {resp.status_code}")
                    return
                print(f"⚠️  Webhook failed: {resp.status_code}")
            except Exception as e:
                print(f"⚠️  Webhook error: {e}")
            time.sleep(delay)
    except Exception as e:
        print(f"⚠️  Webhook error: {e}")

def filter_resume_paths(script_paths: List[Path], resume_path: Path) -> List[Path]:
    try:
        with open(resume_path, 'r', encoding='utf-8') as f:
            prev = json.load(f)
        
        failed_scripts = {
            item.get('script') for item in prev.get('results', [])
            if not bool(item.get('success', False)) and item.get('script')
        }
        
        if failed_scripts:
            return [p for p in script_paths if p.name in failed_scripts]
    except Exception:
        pass
    return script_paths

def install_playwright_browsers() -> bool:
    """Install Playwright browsers."""
    print("🎭 Installing Playwright browsers...")
    try:
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        print("✅ Playwright browsers installed")
        return True
    except subprocess.CalledProcessError:
        print("❌ Failed to install Playwright browsers")
        return False
    except Exception as e:
        print(f"❌ Error installing Playwright browsers: {e}")
        return False

def check_dependencies() -> bool:
    """Check if required dependencies are installed."""
    missing = []
    if not requests:
        missing.append("requests")
    
    try:
        import packaging
    except ImportError:
        missing.append("packaging")

    if missing:
        print(f"❌ Missing required dependencies: {', '.join(missing)}")
        print(f"pip install {' '.join(missing)}")
        return False

    try:
        import bs4
    except ImportError:
        print("⚠️  Warning: Optional 'beautifulsoup4' not found. Some features may be limited.")
        print("pip install beautifulsoup4")

    try:
        import rich
    except ImportError:
        print("ℹ️  Tip: Install 'rich' for nicer progress bars: pip install rich")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ℹ️  Tip: Install 'playwright' for advanced scraping: pip install playwright")
        
    return True

def setup_logging(verbose: bool = False, quiet: bool = False, log_file: Optional[Path] = None) -> None:
    """Configure logging based on verbosity settings."""
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    if LOG_LEVEL != 'INFO':
        level = getattr(logging, LOG_LEVEL, logging.INFO)

    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    
    if log_file:
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        logging.getLogger().addHandler(fh)

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
    exe_grp = parser.add_argument_group('Execution Mode')
    exe_grp.add_argument("--parallel", "-p", action="store_true", default=True, help="Run scripts in parallel (default)")
    exe_grp.add_argument("--sequential", action="store_true", help="Force sequential execution")
    exe_grp.add_argument("--fast", "-f", action="store_true", help="Enable fast mode with optimized worker count")
    exe_grp.add_argument("--install-browsers", action="store_true", help="Install Playwright browsers before running")

    # Performance tuning
    perf_grp = parser.add_argument_group('Performance')
    perf_grp.add_argument("--workers", "-w", type=int, default=DEFAULT_WORKERS, help=f"Number of parallel workers (default: {DEFAULT_WORKERS})")
    perf_grp.add_argument("--timeout", "-t", type=int, default=DEFAULT_TIMEOUT, help=f"Timeout per script in seconds (default: {DEFAULT_TIMEOUT})")
    perf_grp.add_argument("--delay", "-D", type=float, default=0.0, help="Delay (seconds) between scripts in sequential mode")

    # Provider-specific throttling
    throttle_grp = parser.add_argument_group('Provider Throttling')
    throttle_grp.add_argument("--github-workers", type=int, default=MAX_GITHUB_WORKERS, help=f"Max concurrent GitHub-related scripts (default: {MAX_GITHUB_WORKERS})")
    throttle_grp.add_argument("--microsoft-workers", type=int, default=MAX_MICROSOFT_WORKERS, help=f"Max concurrent Microsoft-related scripts (default: {MAX_MICROSOFT_WORKERS})")
    throttle_grp.add_argument("--google-workers", type=int, default=MAX_GOOGLE_WORKERS, help=f"Max concurrent Google-related scripts (default: {MAX_GOOGLE_WORKERS})")

    parser.add_argument("--scripts", "-s", nargs="+", help="Run only specific scripts")
    parser.add_argument("--skip-scripts", nargs="+", help="Skip specific scripts")
    parser.add_argument("--only-providers", nargs="+", choices=["github", "microsoft", "google", "other"], help="Run only scripts classified to these providers")
    parser.add_argument("--skip-providers", nargs="+", choices=["github", "microsoft", "google", "other"], help="Skip scripts classified to these providers")
    parser.add_argument("--dry-run", "-d", action="store_true", help="Show what would be run without executing")
    parser.add_argument("--skip-git", action="store_true", help="Skip git add/commit/push after updates")
    parser.add_argument("--git-per-package", action="store_true", help="Stage & commit each updated manifest individually")
    parser.add_argument("--git-aggregate", action="store_true", help="Stage & commit all changes in aggregate groups")
    parser.add_argument("--git-dry-run", action="store_true", help="Do not push changes, only stage/commit locally")
    parser.add_argument("--git-remote", type=str, help="Remote name to push to")
    parser.add_argument("--git-branch", type=str, help="Branch name to push to")
    parser.add_argument("--structured-output", action="store_true", help="Prefer structured JSON output from update scripts")
    parser.add_argument("--http-cache", action="store_true", help="Enable short-lived HTTP response caching")
    parser.add_argument("--http-cache-ttl", type=int, default=1800, help="HTTP cache TTL in seconds")
    parser.add_argument("--retry", type=int, default=0, help="Number of retry attempts per script on failure")
    parser.add_argument("--json-summary", type=Path, help="Write machine-readable JSON summary")
    parser.add_argument("--md-summary", type=Path, help="Write human-friendly Markdown summary")
    parser.add_argument("--webhook-url", type=str, help="POST the JSON summary to the given webhook URL")
    parser.add_argument("--webhook-type", type=str, choices=["generic", "slack", "discord"], default="generic", help="Webhook payload format")
    parser.add_argument("--webhook-header-name", type=str, help="Optional single HTTP header name for webhook request")
    parser.add_argument("--webhook-header-value", type=str, help="Optional single HTTP header value for webhook request")
    parser.add_argument("--fail-fast", action="store_true", help="Stop sequential execution on first failure")
    parser.add_argument("--max-fail", type=int, default=0, help="Stop sequential execution after N failures")
    parser.add_argument("--circuit-threshold", type=int, default=3, help="Trigger provider pause after N failures (parallel mode)")
    parser.add_argument("--circuit-sleep", type=float, default=5.0, help="Provider pause duration in seconds (parallel mode)")
    parser.add_argument("--resume", type=Path, help="Resume by rerunning only failed scripts from a previous JSON summary")
    parser.add_argument("--no-error-exit", action="store_true", help="Always exit with code 0 even if failures occurred")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--quiet", "-q", action="store_true", help="Reduce logging output")
    parser.add_argument("--log-file", type=Path, help="Write run log to the given file path")

    args = parser.parse_args()

    # Environment overrides for args
    if not args.json_summary and (env_json := os.environ.get('AUTOMATION_JSON_SUMMARY')):
        args.json_summary = Path(env_json)
    if not args.md_summary and (env_md := os.environ.get('AUTOMATION_MD_SUMMARY')):
        args.md_summary = Path(env_md)
    if not args.log_file and (env_log := os.environ.get('AUTOMATION_LOG_FILE')):
        args.log_file = Path(env_log)

    setup_logging(args.verbose, args.quiet, args.log_file)
    
    if args.git_dry_run: os.environ["SCOOP_GIT_DRY_RUN"] = "1"
    if args.git_remote: os.environ["SCOOP_GIT_REMOTE"] = args.git_remote
    if args.git_branch: os.environ["SCOOP_GIT_BRANCH"] = args.git_branch

    global PREFER_STRUCTURED_OUTPUT
    PREFER_STRUCTURED_OUTPUT = bool(args.structured_output)

    if not check_dependencies():
        sys.exit(1)

    if args.install_browsers:
        if not install_playwright_browsers():
            print("⚠️  Proceeding without browser installation...")

    available_scripts = discover_update_scripts()
    scripts_to_run = available_scripts

    if args.scripts:
        selected = []
        available_set = set(available_scripts)
        for s in args.scripts:
            if not s.endswith('.py'):
                s += '.py'
            if not s.startswith('update-'):
                s = f'update-{s}'
            
            if s in available_set:
                selected.append(s)
            else:
                print(f"❌ Unknown script: {s}")
                sys.exit(1)
        scripts_to_run = selected

    if args.skip_scripts:
        def normalize(s):
            if not s.endswith('.py'):
                s += '.py'
            if not s.startswith('update-'):
                s = f'update-{s}'
            return s
            
        skips = {normalize(s) for s in args.skip_scripts}
        scripts_to_run = [s for s in scripts_to_run if s not in skips]

    # Verify existence and convert to Path
    script_paths = [SCRIPTS_DIR / s for s in scripts_to_run if (SCRIPTS_DIR / s).exists()]
    
    if args.resume:
        before = len(script_paths)
        script_paths = filter_resume_paths(script_paths, Path(args.resume))
        print(f"🔁 Resuming: {len(script_paths)} failed script(s) will be rerun" if len(script_paths) < before else "ℹ️  Resume requested but no failed scripts found")

    # Load provider map for filtering
    provider_map = {}
    try:
        if (pmap := SCRIPTS_DIR / 'providers.json').exists():
            with open(pmap, 'r', encoding='utf-8') as f:
                provider_map = json.load(f)
    except Exception:
        pass

    if args.only_providers:
        allowed = set(args.only_providers)
        script_paths = [p for p in script_paths if classify_provider(p, provider_map) in allowed]
        print(f"🎛️ Provider include filter active: {', '.join(allowed)}")

    if args.skip_providers:
        skipped = set(args.skip_providers)
        before_count = len(script_paths)
        script_paths = [p for p in script_paths if classify_provider(p, provider_map) not in skipped]
        print(f"🚫 Provider skip filter active: {', '.join(skipped)} (removed {before_count - len(script_paths)})")

    if not script_paths:
        print("❌ No valid script files found")
        sys.exit(1)

    logging.info("Starting Scoop Bucket Update Orchestrator")
    print("🔧 Scoop Bucket Update Orchestrator")
    print(f"📅 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📂 Scripts directory: {SCRIPTS_DIR}")

    if args.sequential:
        args.parallel = False
        logging.info("Running in sequential mode")
    else:
        args.parallel = True
        logging.info("Running in parallel mode")

    print(f"🎯 Mode: {'Parallel' if args.parallel else 'Sequential'}")
    
    if args.parallel:
        args.workers = max(1, min(args.workers, len(script_paths)))
        print(f"👥 Workers: {args.workers}")
    else:
        print(f"⏳ Sequential delay: {args.delay:.1f}s")

    print(f"⏱️  Timeout: {args.timeout}s per script")
    print(f"📋 Scripts to run ({len(script_paths)}):")
    for p in script_paths:
        print(f"   • {p.stem.replace('update-', '')}")

    if args.dry_run:
        print("\n🔍 DRY RUN - No scripts will be executed")
        return

    print("\n" + "="*80)
    start_time = time.time()

    if args.http_cache:
        os.environ['AUTOMATION_HTTP_CACHE'] = '1'
        os.environ['AUTOMATION_HTTP_CACHE_TTL'] = str(args.http_cache_ttl)
    if args.structured_output:
        os.environ['STRUCTURED_ONLY'] = '1'

    if args.fast:
        args.parallel = True
        recommended = min(6, max(3, (os.cpu_count() or 4)))
        args.workers = min(recommended, len(script_paths))
        print(f"⚡ Fast mode enabled: workers set to {args.workers}")

    if args.parallel:
        results = run_parallel(
            script_paths, args.timeout, args.workers, 
            github_workers=args.github_workers, 
            microsoft_workers=args.microsoft_workers, 
            google_workers=args.google_workers, 
            retries=args.retry, 
            circuit_threshold=args.circuit_threshold, 
            circuit_sleep=args.circuit_sleep
        )
    else:
        results = run_sequential(
            script_paths, args.timeout, args.delay, 
            retries=args.retry, 
            fail_fast=bool(args.fail_fast), 
            max_fail=int(args.max_fail or 0)
        )

    total_duration = time.time() - start_time
    print_summary(results, total_duration)
    
    mode_label = 'Parallel' if args.parallel else 'Sequential'
    write_json_summary(results, total_duration, args, mode_label)
    write_md_summary(results, total_duration, args, mode_label)
    send_webhook_if_configured(args)

    failed_count = len([r for r in results if not r.success])
    if failed_count > 0 and not args.no_error_exit:
        print(f"\n⚠️  {failed_count} script(s) failed")
        sys.exit(1)
    
    if not args.skip_git:
        print("\n" + "-"*80)
        print("🧩 Git integration: staging and committing changes...")
        try:
            if args.git_per_package or not args.git_aggregate:
                updated_results = [r for r in results if r.updated]
                if updated_results:
                    stage_and_commit_per_package(updated_results)
                    
                for app_name, path in list_untracked_manifests():
                    rc, out, err = run_git_command(["git", "add", str(path)])
                    if rc != 0:
                        print(f"⚠️  git add {path} failed: {err or out}")
                        continue
                    
                    version_str = get_manifest_version(app_name)
                    msg = f"{app_name}: Add version {version_str}" if version_str else f"{app_name}: Add manifest"
                    commit_with_message(msg)
                
                push_changes()
            else:
                stage_bucket_changes()
                added_apps, updated_apps = get_staged_bucket_changes()

                if not added_apps and not updated_apps:
                    print("ℹ️  No staged changes found under bucket/ to commit.")
                else:
                    if updated_apps:
                        updated_with_versions = [
                            f"{app} {v}" if (v := get_manifest_version(app)) else app
                            for app in updated_apps
                        ]
                        msg = f"updated ({len(updated_with_versions)}): {', '.join(updated_with_versions)}"
                        print(f"📝 Committing: {msg}")
                        commit_with_message(msg)
                    
                    if added_apps:
                        added_with_versions = [
                            f"{app} {v}" if (v := get_manifest_version(app)) else app
                            for app in added_apps
                        ]
                        msg = f"added ({len(added_with_versions)}): {', '.join(added_with_versions)}"
                        print(f"📝 Committing: {msg}")
                        commit_with_message(msg)
                    
                    push_changes()
        except Exception as e:
            print(f"⚠️  Git integration encountered an error: {e}")

    print(f"\n🎉 All scripts completed successfully!")
    sys.exit(0)

if __name__ == "__main__":
    main()
