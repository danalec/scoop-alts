#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run all Scoop update scripts and summarize the results."""

import argparse
import codecs
import concurrent.futures
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

SCRIPTS_DIR = Path(__file__).parent
sys.path.append(str(SCRIPTS_DIR))

from git_helpers import (
    commit_with_message,
    get_staged_bucket_changes,
    list_untracked_manifests,
    push_changes,
    run_git_command,
    stage_bucket_changes,
)
from summary_utils import format_webhook_body

try:
    import requests
except ImportError:
    requests = None

REPO_ROOT = SCRIPTS_DIR.parent
BUCKET_DIR = REPO_ROOT / "bucket"
SCRIPTS_GLOB = "update-*.py"
MANIFEST_EXTENSION = ".json"
MAX_MANIFEST_SIZE = 10 * 1024 * 1024

DEFAULT_TIMEOUT = int(os.environ.get("SCOOP_UPDATE_TIMEOUT", "120"))
DEFAULT_WORKERS = int(os.environ.get("SCOOP_UPDATE_WORKERS", "6"))
DEFAULT_RETRY_ATTEMPTS = int(os.environ.get("SCOOP_RETRY_ATTEMPTS", "0"))
MAX_GITHUB_WORKERS = int(os.environ.get("MAX_GITHUB_WORKERS", "3"))
MAX_MICROSOFT_WORKERS = int(os.environ.get("MAX_MICROSOFT_WORKERS", "3"))
MAX_GOOGLE_WORKERS = int(os.environ.get("MAX_GOOGLE_WORKERS", "4"))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"

MICROSOFT_DOMAINS = frozenset(
    {
        "learn.microsoft.com",
        "go.microsoft.com",
        "download.microsoft.com",
        "visualstudio.microsoft.com",
    }
)
GOOGLE_DOMAINS = frozenset(
    {
        "googleapis.com",
        "storage.googleapis.com",
        "dl.google.com",
        "cloudfront.net",
    }
)

MANIFEST_VERSION_CACHE: Dict[str, str] = {}
PREFER_STRUCTURED_OUTPUT = False


@dataclass
class UpdateResult:
    """Execution result for a single update script."""

    script_name: str
    success: bool
    output: str
    duration: float
    updated: bool = False


def ensure_utf8_console() -> None:
    """Prefer UTF-8 console streams when running the CLI on Windows."""
    if sys.platform != "win32":
        return

    try:
        if hasattr(sys.stdout, "detach"):
            sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
        if hasattr(sys.stderr, "detach"):
            sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())
    except Exception:
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def package_name_from_script(script_name: str) -> str:
    """Return package name for an update script filename."""
    return script_name.removeprefix("update-").removesuffix(".py")


def normalize_script_name(value: str) -> str:
    """Normalize CLI script input to an update script filename."""
    script_name = value if value.endswith(".py") else f"{value}.py"
    return script_name if script_name.startswith("update-") else f"update-{script_name}"


def get_manifest_version(app_name: str) -> str:
    """Return the manifest version for a package, using an in-memory cache."""
    cached_version = MANIFEST_VERSION_CACHE.get(app_name)
    if cached_version:
        return cached_version

    manifest_path = BUCKET_DIR / f"{app_name}{MANIFEST_EXTENSION}"
    try:
        if manifest_path.stat().st_size > MAX_MANIFEST_SIZE:
            logging.warning("Manifest file too large: %s", manifest_path)
            return ""

        with manifest_path.open("r", encoding="utf-8") as handle:
            version = str(json.load(handle).get("version", "")).strip()
    except FileNotFoundError:
        version = ""
    except Exception as error:
        logging.debug("Failed to read manifest %s: %s", manifest_path, error)
        version = ""

    if version:
        MANIFEST_VERSION_CACHE[app_name] = version
    return version


def resolve_result_version(result: UpdateResult) -> str:
    """Resolve the best available version for summaries and reporting."""
    package = package_name_from_script(result.script_name)

    version = get_manifest_version(package)
    if version:
        return version

    structured = extract_structured_result(result.output)
    structured_version = structured.get("version") if structured else None
    if isinstance(structured_version, str) and structured_version:
        MANIFEST_VERSION_CACHE[package] = structured_version
        return structured_version

    manifest_path = BUCKET_DIR / f"{package}{MANIFEST_EXTENSION}"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    version = str(payload.get("version", "")).strip()
    if version:
        MANIFEST_VERSION_CACHE[package] = version
    return version


def stage_and_commit_per_package(updated_results: Sequence[UpdateResult]) -> None:
    """Stage and commit each updated manifest separately."""
    for result in updated_results:
        package = package_name_from_script(result.script_name)
        manifest_path = BUCKET_DIR / f"{package}{MANIFEST_EXTENSION}"
        if not manifest_path.exists():
            continue

        rc, out, err = run_git_command(["git", "add", str(manifest_path)])
        if rc != 0:
            print(f"⚠️  git add {manifest_path} failed: {err or out}")
            continue

        rc, staged_out, _ = run_git_command(
            ["git", "diff", "--cached", "--name-status", "--", str(manifest_path)]
        )
        if rc != 0 or not staged_out.strip():
            print(f"ℹ️  No staged changes for {package}, skipping commit.")
            continue

        status_line = staged_out.strip().splitlines()[0]
        is_new_file = status_line.split("\t", 1)[0].startswith("A")
        version = get_manifest_version(package)
        action = "Add" if is_new_file else "Update to"
        if version:
            message = f"{package}: {action} version {version} (script: {result.script_name})"
        else:
            message = f"{package}: {action} manifest (script: {result.script_name})"
        commit_with_message(message)


def discover_update_scripts() -> List[str]:
    """Discover all update scripts managed by the orchestrator."""
    scripts = sorted(
        path.name
        for path in SCRIPTS_DIR.glob(SCRIPTS_GLOB)
        if path.name not in {"update-all.py", "update-script-generator.py"}
        and not path.name.startswith("_")
    )

    print(f"🔍 Discovered {len(scripts)} update scripts:")
    for script in scripts:
        print(f"   • {script}")
    return scripts


def extract_structured_result(output: str) -> Optional[Dict[str, object]]:
    """Extract the most relevant JSON status object from script output."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines[-10:]):
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "updated" in parsed:
            return parsed

    match = re.search(r"\{.*\"updated\"\s*:\s*(true|false|null).*\}", output, re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) and "updated" in parsed else None


def parse_script_output(output: str, script_name: str) -> Tuple[bool, bool]:
    """Return ``(updated, no_update_needed)`` for a child script output."""
    structured = extract_structured_result(output)
    if structured is not None:
        package = package_name_from_script(script_name)
        version = structured.get("version")
        if isinstance(version, str):
            MANIFEST_VERSION_CACHE[package] = version
        updated = bool(structured.get("updated"))
        return updated, not updated

    if PREFER_STRUCTURED_OUTPUT:
        return False, False

    lower = output.lower()
    updated = "update completed successfully" in lower or "updated" in lower
    no_update_needed = "no update needed" in lower or "up to date" in lower
    return updated, no_update_needed


def run_update_script(script_path: Path, timeout: int = 300) -> UpdateResult:
    """Run a single update script."""
    script_name = script_path.name
    start_time = time.time()

    try:
        logging.info("Running %s", script_name)
        print(f"🚀 Running {script_name}...")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=SCRIPTS_DIR.parent,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        duration = time.time() - start_time
        output = result.stdout + result.stderr
        updated, no_update_needed = parse_script_output(output, script_name)

        if result.returncode == 0:
            if updated:
                print(f"✅ {script_name} - Updated successfully ({duration:.1f}s)")
            elif no_update_needed:
                print(f"ℹ️  {script_name} - No update needed ({duration:.1f}s)")
            else:
                print(f"✅ {script_name} - Completed ({duration:.1f}s)")
            return UpdateResult(script_name, True, output, duration, updated)

        error_output = result.stderr.strip() or "Unknown error"
        stdout_output = result.stdout.strip()
        details = (
            f"Exit code: {result.returncode}\n"
            f"STDERR: {error_output}\n"
            f"STDOUT: {stdout_output}"
        )
        logging.error("%s failed: %s", script_name, details)
        print(f"❌ {script_name} - Failed ({duration:.1f}s)")
        print(f"   Error details: {details}")
        return UpdateResult(script_name, False, details, duration, False)
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        logging.error("%s timed out after %ss", script_name, timeout)
        print(f"⏰ {script_name} - Timeout after {timeout}s")
        return UpdateResult(
            script_name,
            False,
            f"Script timed out after {timeout} seconds",
            duration,
            False,
        )
    except Exception as error:
        duration = time.time() - start_time
        logging.error("%s error: %s", script_name, error)
        print(f"💥 {script_name} - Error: {error}")
        return UpdateResult(script_name, False, str(error), duration, False)


def run_update_script_with_retry(
    script_path: Path,
    timeout: int = 300,
    retries: int = 0,
) -> UpdateResult:
    """Run a script until it succeeds or retry attempts are exhausted."""
    last_result: Optional[UpdateResult] = None
    for attempt in range(retries + 1):
        result = run_update_script(script_path, timeout)
        if result.success:
            return result
        last_result = result
        if attempt < retries:
            backoff = min(30, 2 ** (attempt + 1))
            print(
                f"🔁 Retrying {script_path.name} in {backoff}s "
                f"(attempt {attempt + 1}/{retries})"
            )
            time.sleep(backoff)

    if last_result is None:
        return UpdateResult(script_path.name, False, "Script did not run", 0.0, False)
    return last_result


def load_provider_map() -> Dict[str, str]:
    """Load optional provider overrides used for throttling and filtering."""
    provider_map_path = SCRIPTS_DIR / "providers.json"
    if not provider_map_path.exists():
        return {}

    try:
        with provider_map_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as error:
        logging.debug("Failed to load provider map: %s", error)
        return {}
    return data if isinstance(data, dict) else {}


def classify_provider(path: Path, provider_map: Dict[str, str]) -> str:
    """Classify a script into a provider bucket."""
    package = package_name_from_script(path.name)
    mapped = provider_map.get(path.name) or provider_map.get(package)
    if isinstance(mapped, str):
        return mapped

    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read(4000)
    except Exception:
        return "other"

    if "github.com" in content or "api.github.com" in content:
        return "github"
    if any(domain in content for domain in MICROSOFT_DOMAINS):
        return "microsoft"
    if any(domain in content for domain in GOOGLE_DOMAINS):
        return "google"
    return "other"


def filter_by_providers(
    scripts: Sequence[Path],
    provider_map: Dict[str, str],
    *,
    only: Optional[Iterable[str]] = None,
    skip: Optional[Iterable[str]] = None,
) -> List[Path]:
    """Filter script paths by classified provider."""
    allowed = set(only or [])
    blocked = set(skip or [])
    filtered: List[Path] = []

    for script_path in scripts:
        provider = classify_provider(script_path, provider_map)
        if allowed and provider not in allowed:
            continue
        if provider in blocked:
            continue
        filtered.append(script_path)

    return filtered


def run_sequential(
    scripts: Sequence[Path],
    timeout: int,
    delay: float = 0.0,
    retries: int = 0,
    *,
    fail_fast: bool = False,
    max_fail: int = 0,
) -> List[UpdateResult]:
    """Run update scripts one by one."""
    results: List[UpdateResult] = []
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


def run_parallel(
    scripts: Sequence[Path],
    timeout: int,
    max_workers: int,
    *,
    github_workers: int = 3,
    microsoft_workers: int = 3,
    google_workers: int = 4,
    retries: int = 0,
    circuit_threshold: int = 3,
    circuit_sleep: float = 5.0,
) -> List[UpdateResult]:
    """Run update scripts in parallel with provider-aware throttling."""
    if not scripts:
        return []

    provider_map = load_provider_map()
    provider_by_script = {path: classify_provider(path, provider_map) for path in scripts}
    counts = Counter(provider_by_script.values())
    max_workers = max(1, min(max_workers, len(scripts)))

    semaphores = {
        "github": threading.BoundedSemaphore(max(1, min(github_workers, max_workers))),
        "microsoft": threading.BoundedSemaphore(max(1, min(microsoft_workers, max_workers))),
        "google": threading.BoundedSemaphore(max(1, min(google_workers, max_workers))),
        "other": threading.BoundedSemaphore(max(1, max_workers)),
    }
    paused_until = {provider: 0.0 for provider in ("github", "microsoft", "google", "other")}
    failure_counts = {provider: 0 for provider in paused_until}
    state_lock = threading.Lock()

    print(
        "🔗 Provider-aware throttling: "
        f"GitHub={counts.get('github', 0)} (max {github_workers}), "
        f"Microsoft={counts.get('microsoft', 0)} (max {microsoft_workers}), "
        f"Google={counts.get('google', 0)} (max {google_workers}), "
        f"Other={counts.get('other', 0)}"
    )

    def task(script_path: Path) -> UpdateResult:
        provider = provider_by_script.get(script_path, "other")
        remaining_pause = paused_until[provider] - time.time()
        if remaining_pause > 0:
            time.sleep(min(circuit_sleep, remaining_pause))

        with semaphores.get(provider, semaphores["other"]):
            return run_update_script_with_retry(script_path, timeout, retries)

    def register_failure(script_path: Path) -> Optional[str]:
        provider = provider_by_script.get(script_path, "other")
        with state_lock:
            failure_counts[provider] += 1
            if circuit_threshold > 0 and failure_counts[provider] >= circuit_threshold:
                paused_until[provider] = time.time() + circuit_sleep
                failure_counts[provider] = 0
                return provider
        return None

    try:
        from rich.progress import (
            BarColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeRemainingColumn,
        )

        rich_available = True
    except ImportError:
        rich_available = False

    results: List[UpdateResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_script = {executor.submit(task, script_path): script_path for script_path in scripts}

        if rich_available:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
            ) as progress:
                task_id = progress.add_task(
                    f"[cyan]Running {len(scripts)} scripts...",
                    total=len(scripts),
                )
                for future in concurrent.futures.as_completed(future_to_script):
                    script_path = future_to_script[future]
                    try:
                        result = future.result()
                    except Exception as error:
                        result = UpdateResult(script_path.name, False, str(error), 0.0, False)
                        progress.console.print(
                            f"[red]💥 {script_path.name} - Unexpected error: {error}[/red]"
                        )
                    results.append(result)
                    progress.advance(task_id)
                    if not result.success:
                        if provider := register_failure(script_path):
                            progress.console.print(
                                f"[yellow]⏸️  Pausing {provider} tasks for "
                                f"{circuit_sleep:.1f}s due to failures[/yellow]"
                            )
        else:
            for future in concurrent.futures.as_completed(future_to_script):
                script_path = future_to_script[future]
                try:
                    result = future.result()
                except Exception as error:
                    result = UpdateResult(script_path.name, False, str(error), 0.0, False)
                    print(f"💥 {script_path.name} - Unexpected error: {error}")
                results.append(result)
                if not result.success:
                    if provider := register_failure(script_path):
                        print(
                            f"⏸️  Pausing {provider} tasks for {circuit_sleep:.1f}s "
                            "due to failures"
                        )

    results.sort(key=lambda item: item.script_name)
    return results


def summarize_results(results: Sequence[UpdateResult]) -> Dict[str, object]:
    """Build grouped result lists and counters."""
    successful = [result for result in results if result.success]
    failed = [result for result in results if not result.success]
    updated = [result for result in results if result.updated]
    no_updates = [result for result in successful if not result.updated]
    return {
        "successful": successful,
        "failed": failed,
        "updated": updated,
        "no_updates": no_updates,
        "counts": {
            "total": len(results),
            "successful": len(successful),
            "failed": len(failed),
            "updated": len(updated),
            "no_updates": len(no_updates),
        },
    }


def print_summary(results: Sequence[UpdateResult], total_duration: float) -> None:
    """Print a human-readable execution summary."""
    summary = summarize_results(results)
    counts = summary["counts"]
    updated = summary["updated"]
    failed = summary["failed"]
    no_updates = summary["no_updates"]

    print("\n" + "=" * 80)
    print("📊 UPDATE SUMMARY")
    print("=" * 80)
    print(f"📈 Total Scripts: {counts['total']}")
    print(f"✅ Successful: {counts['successful']}")
    print(f"❌ Failed: {counts['failed']}")
    print(f"🔄 Updated: {counts['updated']}")
    print(f"⏱️  Total Duration: {total_duration:.1f}s")

    if updated:
        print("\n🎉 PACKAGES UPDATED:")
        for result in updated:
            package = package_name_from_script(result.script_name)
            version = resolve_result_version(result)
            if version:
                print(f"   • {package}: Update to version {version} ({result.duration:.1f}s)")
            else:
                print(f"   • {package} ({result.duration:.1f}s)")

    if failed:
        print("\n❌ FAILED SCRIPTS:")
        for result in failed:
            print(f"   • {result.script_name} ({result.duration:.1f}s)")
            for line in result.output.strip().splitlines()[:3]:
                if line.strip():
                    print(f"     {line.strip()}")

    if no_updates:
        print("\nℹ️  NO UPDATES NEEDED:")
        for result in no_updates:
            package = package_name_from_script(result.script_name)
            version = resolve_result_version(result)
            if version:
                print(f"   • {package} (version {version})")
            else:
                print(f"   • {package}")

    print("\n" + "=" * 80)


def write_json_summary(
    results: Sequence[UpdateResult],
    total_duration: float,
    args: argparse.Namespace,
    mode_label: str,
) -> None:
    """Write a machine-readable summary file."""
    if not args.json_summary:
        return

    try:
        summary_path = Path(args.json_summary)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary = summarize_results(results)
        counts = summary["counts"]

        data = {
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "mode": mode_label,
            "timeout": args.timeout,
            "workers": args.workers if args.parallel else 1,
            "provider_workers": {
                "github": args.github_workers,
                "microsoft": args.microsoft_workers,
                "google": args.google_workers,
            },
            "total_duration_seconds": round(total_duration, 3),
            "counts": counts,
            "results": [],
        }

        for result in results:
            package = package_name_from_script(result.script_name)
            version = resolve_result_version(result)
            data["results"].append(
                {
                    "script": result.script_name,
                    "package": package,
                    "success": result.success,
                    "updated": result.updated,
                    "duration_seconds": round(result.duration, 3),
                    "version": version,
                    "error_preview": (
                        "\n".join(result.output.strip().splitlines()[:3])
                        if not result.success
                        else ""
                    ),
                }
            )

        summary_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"🧾 JSON summary written to: {summary_path}")
    except Exception as error:
        print(f"⚠️  Failed to write JSON summary: {error}")


def write_md_summary(
    results: Sequence[UpdateResult],
    total_duration: float,
    args: argparse.Namespace,
    mode_label: str,
) -> None:
    """Write a Markdown dashboard summary."""
    if not getattr(args, "md_summary", None):
        return

    try:
        out_path = Path(args.md_summary)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        summary = summarize_results(results)
        counts = summary["counts"]

        lines = [
            "# Update Health Dashboard",
            "",
            f"- Mode: {mode_label}",
            f"- Total: {counts['total']}",
            f"- Successful: {counts['successful']}",
            f"- Failed: {counts['failed']}",
            f"- Updated: {counts['updated']}",
            f"- Duration (s): {round(total_duration, 3)}",
            "",
            "| Package | Version | Success | Updated | Duration (s) |",
            "|---|---|---|---|---|",
        ]

        for result in results:
            package = package_name_from_script(result.script_name)
            version = resolve_result_version(result)
            lines.append(
                f"| {package} | {version} | {result.success} | {result.updated} | "
                f"{round(result.duration, 3)} |"
            )

        out_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"🧾 Markdown summary written to: {out_path}")
    except Exception as error:
        print(f"⚠️  Failed to write Markdown summary: {error}")


def send_webhook_if_configured(args: argparse.Namespace) -> None:
    """Post the JSON summary to a webhook if webhook settings are present."""
    if not args.webhook_url or not args.json_summary:
        return
    if requests is None:
        print("⚠️  Webhook skipped: requests library not installed")
        return

    try:
        payload = json.loads(Path(args.json_summary).read_text(encoding="utf-8"))
    except Exception as error:
        print(f"⚠️  Webhook skipped: cannot read summary file: {error}")
        return

    headers = {"Content-Type": "application/json"}
    if args.webhook_header_name and args.webhook_header_value:
        headers[args.webhook_header_name] = args.webhook_header_value

    body = format_webhook_body(payload, getattr(args, "webhook_type", "generic"))
    for delay in (0.5, 1.0, 2.0):
        try:
            response = requests.post(args.webhook_url, json=body, headers=headers, timeout=15)
            if 200 <= response.status_code < 300:
                print(f"📣 Webhook delivered: {response.status_code}")
                return
            print(f"⚠️  Webhook failed: {response.status_code}")
        except Exception as error:
            print(f"⚠️  Webhook error: {error}")
        time.sleep(delay)


def filter_resume_paths(script_paths: Sequence[Path], resume_path: Path) -> List[Path]:
    """Keep only scripts that failed in a previous JSON summary."""
    try:
        previous = json.loads(resume_path.read_text(encoding="utf-8"))
    except Exception:
        return list(script_paths)

    failed_scripts = {
        item.get("script")
        for item in previous.get("results", [])
        if not bool(item.get("success", False)) and item.get("script")
    }
    if not failed_scripts:
        return list(script_paths)
    return [path for path in script_paths if path.name in failed_scripts]


def install_playwright_browsers() -> bool:
    """Install Playwright browsers."""
    print("🎭 Installing Playwright browsers...")
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True,
        )
        print("✅ Playwright browsers installed")
        return True
    except subprocess.CalledProcessError:
        print("❌ Failed to install Playwright browsers")
        return False
    except Exception as error:
        print(f"❌ Error installing Playwright browsers: {error}")
        return False


def check_dependencies() -> bool:
    """Check required and optional Python dependencies."""
    if requests is None:
        print("❌ Missing required dependency: requests")
        print("pip install requests")
        return False

    try:
        import bs4  # noqa: F401
    except ImportError:
        print("ℹ️  Tip: Install 'beautifulsoup4' for parsers that depend on it.")

    try:
        import packaging  # noqa: F401
    except ImportError:
        print("ℹ️  Tip: Install 'packaging' for stronger semantic version ordering.")

    try:
        import rich  # noqa: F401
    except ImportError:
        print("ℹ️  Tip: Install 'rich' for nicer progress bars.")

    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        print("ℹ️  Tip: Install 'playwright' for advanced scraping.")

    return True


def setup_logging(
    verbose: bool = False,
    quiet: bool = False,
    log_file: Optional[Path] = None,
) -> None:
    """Configure console and optional file logging."""
    if quiet:
        level = logging.WARNING
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    if LOG_LEVEL != "INFO":
        level = getattr(logging, LOG_LEVEL, logging.INFO)

    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    if log_file:
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        logging.getLogger().addHandler(file_handler)


def apply_environment_overrides(args: argparse.Namespace) -> None:
    """Populate CLI arguments from environment defaults when absent."""
    if not args.json_summary and (env_json := os.environ.get("AUTOMATION_JSON_SUMMARY")):
        args.json_summary = Path(env_json)
    if not args.md_summary and (env_md := os.environ.get("AUTOMATION_MD_SUMMARY")):
        args.md_summary = Path(env_md)
    if not args.log_file and (env_log := os.environ.get("AUTOMATION_LOG_FILE")):
        args.log_file = Path(env_log)


def configure_runtime_environment(args: argparse.Namespace) -> None:
    """Propagate runtime settings to child processes via environment variables."""
    if args.git_dry_run:
        os.environ["SCOOP_GIT_DRY_RUN"] = "1"
    if args.git_remote:
        os.environ["SCOOP_GIT_REMOTE"] = args.git_remote
    if args.git_branch:
        os.environ["SCOOP_GIT_BRANCH"] = args.git_branch
    if args.http_cache:
        os.environ["AUTOMATION_HTTP_CACHE"] = "1"
        os.environ["AUTOMATION_HTTP_CACHE_TTL"] = str(args.http_cache_ttl)
    if args.structured_output:
        os.environ["STRUCTURED_ONLY"] = "1"


def resolve_script_selection(
    available_scripts: Sequence[str],
    selected_scripts: Optional[Sequence[str]],
) -> List[str]:
    """Resolve requested scripts against the discovered script list."""
    if not selected_scripts:
        return list(available_scripts)

    available_set = set(available_scripts)
    resolved: List[str] = []
    for raw_name in selected_scripts:
        script_name = normalize_script_name(raw_name)
        if script_name not in available_set:
            print(f"❌ Unknown script: {script_name}")
            sys.exit(1)
        resolved.append(script_name)
    return resolved


def prepare_script_paths(args: argparse.Namespace) -> List[Path]:
    """Build the final list of script paths to execute."""
    available_scripts = discover_update_scripts()
    scripts_to_run = resolve_script_selection(available_scripts, args.scripts)

    if args.skip_scripts:
        skipped = {normalize_script_name(name) for name in args.skip_scripts}
        scripts_to_run = [name for name in scripts_to_run if name not in skipped]

    script_paths = [SCRIPTS_DIR / name for name in scripts_to_run if (SCRIPTS_DIR / name).exists()]

    if args.resume:
        before_count = len(script_paths)
        script_paths = filter_resume_paths(script_paths, Path(args.resume))
        if len(script_paths) < before_count:
            print(f"🔁 Resuming: {len(script_paths)} failed script(s) will be rerun")
        else:
            print("ℹ️  Resume requested but no failed scripts found")

    provider_map = load_provider_map()
    if args.only_providers:
        script_paths = filter_by_providers(script_paths, provider_map, only=args.only_providers)
        print(f"🎛️ Provider include filter active: {', '.join(args.only_providers)}")
    if args.skip_providers:
        before_count = len(script_paths)
        script_paths = filter_by_providers(script_paths, provider_map, skip=args.skip_providers)
        removed_count = before_count - len(script_paths)
        print(
            f"🚫 Provider skip filter active: {', '.join(args.skip_providers)} "
            f"(removed {removed_count})"
        )

    return script_paths


def handle_git_integration(args: argparse.Namespace, results: Sequence[UpdateResult]) -> None:
    """Stage, commit, and optionally push updated manifests."""
    if args.skip_git:
        return

    print("\n" + "-" * 80)
    print("🧩 Git integration: staging and committing changes...")

    try:
        if args.git_per_package or not args.git_aggregate:
            updated_results = [result for result in results if result.updated]
            if updated_results:
                stage_and_commit_per_package(updated_results)

            for app_name, path in list_untracked_manifests():
                rc, out, err = run_git_command(["git", "add", str(path)])
                if rc != 0:
                    print(f"⚠️  git add {path} failed: {err or out}")
                    continue

                version = get_manifest_version(app_name)
                message = f"{app_name}: Add version {version}" if version else f"{app_name}: Add manifest"
                commit_with_message(message)

            push_changes()
            return

        stage_bucket_changes()
        added_apps, updated_apps = get_staged_bucket_changes()

        if not added_apps and not updated_apps:
            print("ℹ️  No staged changes found under bucket/ to commit.")
            return

        if updated_apps:
            updated_with_versions = [
                f"{app} {version}" if (version := get_manifest_version(app)) else app
                for app in updated_apps
            ]
            message = f"updated ({len(updated_with_versions)}): {', '.join(updated_with_versions)}"
            print(f"📝 Committing: {message}")
            commit_with_message(message)

        if added_apps:
            added_with_versions = [
                f"{app} {version}" if (version := get_manifest_version(app)) else app
                for app in added_apps
            ]
            message = f"added ({len(added_with_versions)}): {', '.join(added_with_versions)}"
            print(f"📝 Committing: {message}")
            commit_with_message(message)

        push_changes()
    except Exception as error:
        print(f"⚠️  Git integration encountered an error: {error}")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Run all Scoop bucket update scripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/update-all.py
  python scripts/update-all.py --sequential
  python scripts/update-all.py --workers 8
  python scripts/update-all.py --scripts corecycler esptool
  python scripts/update-all.py --fast --retry 2
        """,
    )

    execution_group = parser.add_argument_group("Execution Mode")
    execution_group.add_argument(
        "--parallel",
        "-p",
        action="store_true",
        default=True,
        help="Run scripts in parallel (default)",
    )
    execution_group.add_argument(
        "--sequential",
        action="store_true",
        help="Force sequential execution",
    )
    execution_group.add_argument(
        "--fast",
        "-f",
        action="store_true",
        help="Enable fast mode with optimized worker count",
    )
    execution_group.add_argument(
        "--install-browsers",
        action="store_true",
        help="Install Playwright browsers before running",
    )

    performance_group = parser.add_argument_group("Performance")
    performance_group.add_argument(
        "--workers",
        "-w",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of parallel workers (default: {DEFAULT_WORKERS})",
    )
    performance_group.add_argument(
        "--timeout",
        "-t",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout per script in seconds (default: {DEFAULT_TIMEOUT})",
    )
    performance_group.add_argument(
        "--delay",
        "-D",
        type=float,
        default=0.0,
        help="Delay between scripts in sequential mode",
    )

    throttle_group = parser.add_argument_group("Provider Throttling")
    throttle_group.add_argument(
        "--github-workers",
        type=int,
        default=MAX_GITHUB_WORKERS,
        help=f"Max concurrent GitHub-related scripts (default: {MAX_GITHUB_WORKERS})",
    )
    throttle_group.add_argument(
        "--microsoft-workers",
        type=int,
        default=MAX_MICROSOFT_WORKERS,
        help=f"Max concurrent Microsoft-related scripts (default: {MAX_MICROSOFT_WORKERS})",
    )
    throttle_group.add_argument(
        "--google-workers",
        type=int,
        default=MAX_GOOGLE_WORKERS,
        help=f"Max concurrent Google-related scripts (default: {MAX_GOOGLE_WORKERS})",
    )

    parser.add_argument("--scripts", "-s", nargs="+", help="Run only specific scripts")
    parser.add_argument("--skip-scripts", nargs="+", help="Skip specific scripts")
    parser.add_argument(
        "--only-providers",
        nargs="+",
        choices=["github", "microsoft", "google", "other"],
        help="Run only scripts classified to these providers",
    )
    parser.add_argument(
        "--skip-providers",
        nargs="+",
        choices=["github", "microsoft", "google", "other"],
        help="Skip scripts classified to these providers",
    )
    parser.add_argument("--dry-run", "-d", action="store_true", help="Show what would be run")
    parser.add_argument("--skip-git", action="store_true", help="Skip git add/commit/push")
    parser.add_argument(
        "--git-per-package",
        action="store_true",
        help="Stage and commit each updated manifest individually",
    )
    parser.add_argument(
        "--git-aggregate",
        action="store_true",
        help="Stage and commit all changes in aggregate groups",
    )
    parser.add_argument("--git-dry-run", action="store_true", help="Stage and commit without pushing")
    parser.add_argument("--git-remote", type=str, help="Remote name to push to")
    parser.add_argument("--git-branch", type=str, help="Branch name to push to")
    parser.add_argument(
        "--structured-output",
        action="store_true",
        help="Prefer structured JSON output from update scripts",
    )
    parser.add_argument(
        "--http-cache",
        action="store_true",
        help="Enable short-lived HTTP response caching",
    )
    parser.add_argument("--http-cache-ttl", type=int, default=1800, help="HTTP cache TTL in seconds")
    parser.add_argument(
        "--retry",
        type=int,
        default=DEFAULT_RETRY_ATTEMPTS,
        help="Number of retry attempts per script",
    )
    parser.add_argument("--json-summary", type=Path, help="Write machine-readable JSON summary")
    parser.add_argument("--md-summary", type=Path, help="Write human-friendly Markdown summary")
    parser.add_argument("--webhook-url", type=str, help="POST the JSON summary to a webhook URL")
    parser.add_argument(
        "--webhook-type",
        type=str,
        choices=["generic", "slack", "discord"],
        default="generic",
        help="Webhook payload format",
    )
    parser.add_argument("--webhook-header-name", type=str, help="Optional webhook header name")
    parser.add_argument("--webhook-header-value", type=str, help="Optional webhook header value")
    parser.add_argument("--fail-fast", action="store_true", help="Stop sequential execution on first failure")
    parser.add_argument("--max-fail", type=int, default=0, help="Stop sequential execution after N failures")
    parser.add_argument(
        "--circuit-threshold",
        type=int,
        default=3,
        help="Trigger provider pause after N failures in parallel mode",
    )
    parser.add_argument(
        "--circuit-sleep",
        type=float,
        default=5.0,
        help="Provider pause duration in seconds in parallel mode",
    )
    parser.add_argument(
        "--resume",
        type=Path,
        help="Resume by rerunning only failed scripts from a previous JSON summary",
    )
    parser.add_argument(
        "--no-error-exit",
        action="store_true",
        help="Always exit with code 0 even if failures occurred",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--quiet", "-q", action="store_true", help="Reduce logging output")
    parser.add_argument("--log-file", type=Path, help="Write run log to the given file path")
    return parser


def main() -> None:
    """Entry point for the update orchestrator."""
    ensure_utf8_console()
    parser = build_parser()
    args = parser.parse_args()

    apply_environment_overrides(args)
    setup_logging(args.verbose, args.quiet, args.log_file)
    configure_runtime_environment(args)

    global PREFER_STRUCTURED_OUTPUT
    PREFER_STRUCTURED_OUTPUT = bool(args.structured_output)

    if not check_dependencies():
        sys.exit(1)

    if args.install_browsers and not install_playwright_browsers():
        print("⚠️  Proceeding without browser installation...")

    script_paths = prepare_script_paths(args)
    if not script_paths:
        print("❌ No valid script files found")
        sys.exit(1)

    if args.fast:
        args.parallel = True
        recommended_workers = min(6, max(3, (os.cpu_count() or 4)))
        args.workers = min(recommended_workers, len(script_paths))
        print(f"⚡ Fast mode enabled: workers set to {args.workers}")

    if args.sequential:
        args.parallel = False
    else:
        args.parallel = True

    logging.info("Starting Scoop Bucket Update Orchestrator")
    print("🔧 Scoop Bucket Update Orchestrator")
    print(f"📅 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📂 Scripts directory: {SCRIPTS_DIR}")
    print(f"🎯 Mode: {'Parallel' if args.parallel else 'Sequential'}")

    if args.parallel:
        args.workers = max(1, min(args.workers, len(script_paths)))
        print(f"👥 Workers: {args.workers}")
    else:
        print(f"⏳ Sequential delay: {args.delay:.1f}s")

    print(f"⏱️  Timeout: {args.timeout}s per script")
    print(f"📋 Scripts to run ({len(script_paths)}):")
    for script_path in script_paths:
        print(f"   • {package_name_from_script(script_path.name)}")

    if args.dry_run:
        print("\n🔍 DRY RUN - No scripts will be executed")
        return

    print("\n" + "=" * 80)
    start_time = time.time()

    if args.parallel:
        results = run_parallel(
            script_paths,
            args.timeout,
            args.workers,
            github_workers=args.github_workers,
            microsoft_workers=args.microsoft_workers,
            google_workers=args.google_workers,
            retries=args.retry,
            circuit_threshold=args.circuit_threshold,
            circuit_sleep=args.circuit_sleep,
        )
    else:
        results = run_sequential(
            script_paths,
            args.timeout,
            args.delay,
            retries=args.retry,
            fail_fast=bool(args.fail_fast),
            max_fail=int(args.max_fail or 0),
        )

    total_duration = time.time() - start_time
    print_summary(results, total_duration)

    mode_label = "Parallel" if args.parallel else "Sequential"
    write_json_summary(results, total_duration, args, mode_label)
    write_md_summary(results, total_duration, args, mode_label)
    send_webhook_if_configured(args)

    failed_count = len([result for result in results if not result.success])
    if failed_count > 0 and not args.no_error_exit:
        print(f"\n⚠️  {failed_count} script(s) failed")
        sys.exit(1)

    handle_git_integration(args, results)
    print("\n🎉 All scripts completed successfully!")
    sys.exit(0)


if __name__ == "__main__":
    main()
