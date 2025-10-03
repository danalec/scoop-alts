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
from typing import List, Tuple, Dict

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())

# Configuration
SCRIPTS_DIR = Path(__file__).parent

def discover_update_scripts() -> List[str]:
    """Automatically discover all update-*.py scripts in the scripts directory"""
    update_scripts = []
    
    # Find all update-*.py files
    for script_file in SCRIPTS_DIR.glob("update-*.py"):
        # Skip the update-all.py script itself and utility scripts
        if script_file.name not in ["update-all.py", "update-script-generator.py"]:
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

def run_update_script(script_path: Path, timeout: int = 300) -> UpdateResult:
    """Run a single update script and return the result."""
    script_name = script_path.name
    start_time = time.time()
    
    try:
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
        updated = "update completed successfully" in output.lower() or "updated" in output.lower()
        no_update_needed = "no update needed" in output.lower() or "up to date" in output.lower()
        
        if result.returncode == 0:
            if updated:
                print(f"✅ {script_name} - Updated successfully ({duration:.1f}s)")
            elif no_update_needed:
                print(f"ℹ️  {script_name} - No update needed ({duration:.1f}s)")
            else:
                print(f"✅ {script_name} - Completed ({duration:.1f}s)")
            
            return UpdateResult(script_name, True, output, duration, updated)
        else:
            error_msg = result.stderr.strip() if result.stderr else 'Unknown error'
            stdout_msg = result.stdout.strip() if result.stdout else ''
            detailed_error = f"Exit code: {result.returncode}\nSTDERR: {error_msg}\nSTDOUT: {stdout_msg}"
            print(f"❌ {script_name} - Failed ({duration:.1f}s)")
            print(f"   Error details: {detailed_error}")
            return UpdateResult(script_name, False, detailed_error, duration, False)
            
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        print(f"⏰ {script_name} - Timeout after {timeout}s")
        return UpdateResult(script_name, False, f"Script timed out after {timeout} seconds", duration, False)
        
    except Exception as e:
        duration = time.time() - start_time
        print(f"💥 {script_name} - Error: {e}")
        return UpdateResult(script_name, False, str(e), duration, False)

def run_sequential(scripts: List[Path], timeout: int, delay: float = 0.0) -> List[UpdateResult]:
    """Run update scripts sequentially.

    Args:
        scripts: List of script paths to run
        timeout: Timeout per script in seconds
        delay: Optional delay (in seconds) between scripts to avoid overwhelming APIs
    """
    results = []
    
    for script_path in scripts:
        result = run_update_script(script_path, timeout)
        results.append(result)
        
        # Optional delay between scripts
        if delay and delay > 0:
            time.sleep(delay)
    
    return results

def run_parallel(scripts: List[Path], timeout: int, max_workers: int) -> List[UpdateResult]:
    """Run update scripts in parallel."""
    results = []
    
    # Cap workers to the number of scripts to avoid oversubscription
    max_workers = max(1, min(max_workers, len(scripts)))
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all scripts
        future_to_script = {
            executor.submit(run_update_script, script_path, timeout): script_path 
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
            print(f"   • {result.script_name.replace('update-', '').replace('.py', '')} ({result.duration:.1f}s)")
    
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
            print(f"   • {package_name}")
    
    print("\n" + "="*80)

def check_dependencies():
    """Check if required dependencies are installed."""
    try:
        import requests
        import packaging
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please install required packages:")
        print("pip install requests packaging")
        return False
    
    # Check for BeautifulSoup (needed for website scraping scripts)
    try:
        import bs4
    except ImportError:
        print("⚠️  Warning: BeautifulSoup4 not found. Website scraping scripts may fail.")
        print("Install with: pip install beautifulsoup4")
    
    return True

def main():
    """Main function to orchestrate all update scripts."""
    parser = argparse.ArgumentParser(description="Run all Scoop bucket update scripts")
    parser.add_argument("--parallel", "-p", action="store_true", 
                       help="Run scripts in parallel (faster but may hit API limits)")
    parser.add_argument("--workers", "-w", type=int, default=3,
                       help="Number of parallel workers (default: 3)")
    parser.add_argument("--delay", "-D", type=float, default=0.5,
                       help="Delay (seconds) between scripts in sequential mode (default: 0.5)")
    parser.add_argument("--fast", "-f", action="store_true",
                       help="Enable fast mode: parallel execution with an optimized worker count")
    parser.add_argument("--timeout", "-t", type=int, default=300,
                       help="Timeout per script in seconds (default: 300)")
    parser.add_argument("--scripts", "-s", nargs="+", 
                       help="Run only specific scripts (e.g., corecycler esptool)")
    parser.add_argument("--dry-run", "-d", action="store_true",
                       help="Show what would be run without executing")
    
    args = parser.parse_args()
    
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
    print("🔧 Scoop Bucket Update Orchestrator")
    print(f"📅 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📂 Scripts directory: {SCRIPTS_DIR}")
    print(f"🎯 Mode: {'Parallel' if args.parallel else 'Sequential'}")
    if args.parallel:
        print(f"👥 Workers: {args.workers}")
    else:
        print(f"⏳ Sequential delay: {args.delay:.1f}s")
    print(f"⏱️  Timeout: {args.timeout}s per script")
    print(f"📋 Scripts to run ({len(script_paths)}):")
    
    for script_path in script_paths:
        package_name = script_path.name.replace('update-', '').replace('.py', '')
        print(f"   • {package_name}")
    
    if args.dry_run:
        print("\n🔍 DRY RUN - No scripts will be executed")
        return
    
    print("\n" + "="*80)
    
    # Run the scripts
    start_time = time.time()
    
    # If fast mode is enabled, force parallel with an optimized worker count
    if args.fast:
        args.parallel = True
        # Recommend worker count based on CPU and script count (network-bound tasks benefit from moderate concurrency)
        recommended_workers = min(6, max(3, (os.cpu_count() or 4)))
        args.workers = min(recommended_workers, len(script_paths))
        print(f"⚡ Fast mode enabled: workers set to {args.workers}")
    
    if args.parallel:
        results = run_parallel(script_paths, args.timeout, args.workers)
    else:
        results = run_sequential(script_paths, args.timeout, args.delay)
    
    total_duration = time.time() - start_time
    
    # Print summary
    print_summary(results, total_duration)
    
    # Exit with appropriate code
    failed_count = len([r for r in results if not r.success])
    if failed_count > 0:
        print(f"\n⚠️  {failed_count} script(s) failed")
        sys.exit(1)
    else:
        print(f"\n🎉 All scripts completed successfully!")
        sys.exit(0)

if __name__ == "__main__":
    main()