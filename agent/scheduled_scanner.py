"""
Scheduled Scanner — runs in GitHub Actions
Checks Supabase settings before scanning.
If weekly_scan_enabled=false, exits early (scan is "paused").

Environment variables needed:
  ANTHROPIC_API_KEY
  SUPABASE_URL
  SUPABASE_KEY
  FORCE_SCAN=true/false   (override the enabled flag)
  OVERRIDE_REPOS=repo1,repo2  (override configured repos)
  SCAN_MODE=scheduled|manual
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FORCE_SCAN = os.environ.get("FORCE_SCAN", "false").lower() == "true"
OVERRIDE_REPOS = os.environ.get("OVERRIDE_REPOS", "").strip()
SCAN_MODE = os.environ.get("SCAN_MODE", "scheduled")


def supabase_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def get_settings() -> dict | None:
    """Fetch settings from Supabase."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/settings",
            headers=supabase_headers(),
            params={"id": "eq.1", "select": "*"},
        )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0]
        return None


async def update_scan_timestamps() -> None:
    """Update last_scan_at and next_scan_at in settings."""
    now = datetime.now(timezone.utc).isoformat()
    # Next scan = next Monday
    from datetime import timedelta
    today = datetime.now(timezone.utc)
    days_until_monday = (7 - today.weekday()) % 7 or 7
    next_monday = (today + timedelta(days=days_until_monday)).replace(
        hour=8, minute=0, second=0, microsecond=0
    )

    async with httpx.AsyncClient() as client:
        await client.patch(
            f"{SUPABASE_URL}/rest/v1/settings",
            headers=supabase_headers(),
            params={"id": "eq.1"},
            json={
                "last_scan_at": now,
                "next_scan_at": next_monday.isoformat(),
                "updated_at": now,
            },
        )


async def save_report_to_supabase(
    repo_name: str,
    language: str,
    findings: list[dict],
    ai_summary: str,
    repo_path: str = "",
) -> str | None:
    """Save scan results directly to Supabase."""
    critical = sum(1 for f in findings if f.get("severity") == "critical")
    high = sum(1 for f in findings if f.get("severity") == "high")
    medium = sum(1 for f in findings if f.get("severity") == "medium")
    low = sum(1 for f in findings if f.get("severity") == "low")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Insert report
        resp = await client.post(
            f"{SUPABASE_URL}/rest/v1/reports",
            headers=supabase_headers(),
            json={
                "repo_name": repo_name,
                "repo_path": repo_path,
                "language": language,
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "total_findings": len(findings),
                "critical": critical,
                "high": high,
                "medium": medium,
                "low": low,
                "ai_summary": ai_summary,
            },
        )
        if resp.status_code not in (200, 201):
            print(f"  ❌ Failed to save report: {resp.status_code}")
            return None

        report_id = resp.json()[0]["id"]

        # Insert findings in batches
        if findings:
            batch_size = 100
            for i in range(0, len(findings), batch_size):
                batch = findings[i:i + batch_size]
                await client.post(
                    f"{SUPABASE_URL}/rest/v1/findings",
                    headers=supabase_headers(),
                    json=[
                        {
                            "report_id": report_id,
                            "file": f.get("file", ""),
                            "line": f.get("line", 0),
                            "severity": f.get("severity", "low"),
                            "category": f.get("category", "general"),
                            "title": f.get("title", ""),
                            "description": f.get("description", ""),
                            "suggested_fix": f.get("suggested_fix", ""),
                            "language": language,
                        }
                        for f in batch
                    ],
                )

        return report_id


async def scan_kotlin_repo(repo_path: str, repo_name: str) -> None:
    """Scan a Kotlin/Android repository."""
    print(f"\n  🤖 Scanning Kotlin: {repo_name}")
    try:
        # Import and run the Kotlin scanner
        sys.path.insert(0, str(Path(__file__).parent))
        from bug_agent import scan_repo as kotlin_scan
        report = await kotlin_scan(repo_path)
        findings = [f.model_dump() for f in report.findings]
        report_id = await save_report_to_supabase(
            repo_name, "kotlin", findings, report.ai_summary, repo_path
        )
        print(f"  ✅ Kotlin: {len(findings)} findings → Supabase {report_id[:8] if report_id else 'failed'}")
    except Exception as e:
        print(f"  ❌ Kotlin scan failed: {e}")


async def scan_typescript_repo(repo_path: str, repo_name: str) -> None:
    """Scan a TypeScript/Next.js repository."""
    print(f"\n  📘 Scanning TypeScript: {repo_name}")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from ts_agent import scan_repo as ts_scan
        report = await ts_scan(repo_path)
        findings = [f.model_dump() for f in report.findings]
        report_id = await save_report_to_supabase(
            repo_name, "typescript", findings, report.ai_summary, repo_path
        )
        print(f"  ✅ TypeScript: {len(findings)} findings → Supabase {report_id[:8] if report_id else 'failed'}")
    except Exception as e:
        print(f"  ❌ TypeScript scan failed: {e}")


async def scan_javascript_repo(repo_path: str, repo_name: str) -> None:
    """Scan a JavaScript repository."""
    print(f"\n  💛 Scanning JavaScript: {repo_name}")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from js_agent import scan_repo as js_scan
        report = await js_scan(repo_path)
        findings = [f.model_dump() for f in report.findings]
        report_id = await save_report_to_supabase(
            repo_name, "javascript", findings, report.ai_summary, repo_path
        )
        print(f"  ✅ JavaScript: {len(findings)} findings → Supabase {report_id[:8] if report_id else 'failed'}")
    except Exception as e:
        print(f"  ❌ JavaScript scan failed: {e}")


async def scan_java_repo(repo_path: str, repo_name: str) -> None:
    """Scan a Java/Spring repository."""
    print(f"\n  ☕ Scanning Java: {repo_name}")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from java_agent import scan_repo as java_scan
        report = await java_scan(repo_path)
        findings = [f.model_dump() for f in report.findings]
        report_id = await save_report_to_supabase(
            repo_name, "java", findings, report.ai_summary, repo_path
        )
        print(f"  ✅ Java: {len(findings)} findings → Supabase {report_id[:8] if report_id else 'failed'}")
    except Exception as e:
        print(f"  ❌ Java scan failed: {e}")


# Repo name → (local path, language)
# In GitHub Actions the repos are cloned fresh
REPO_CONFIG = {
    "DailyPulse":       ("/tmp/repos/DailyPulse",       "kotlin",      "https://github.com/Dicky59/daily-pulse"),
    "next-store":       ("/tmp/repos/next-store",        "typescript",  "https://github.com/Dicky59/next-store"),
    "next-dicky":       ("/tmp/repos/next-dicky",        "javascript",  "https://github.com/Dicky59/next-dicky"),
    "spring-petclinic": ("/tmp/repos/spring-petclinic",  "java",        "https://github.com/spring-projects/spring-petclinic"),
}

SCAN_FUNCTIONS = {
    "kotlin":     scan_kotlin_repo,
    "typescript": scan_typescript_repo,
    "javascript": scan_javascript_repo,
    "java":       scan_java_repo,
}


async def clone_repo(name: str, url: str, path: str) -> bool:
    """Clone a repo to a temp path."""
    import subprocess
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if Path(path).exists():
        return True
    result = subprocess.run(
        ["git", "clone", "--depth=1", url, path],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  ❌ Clone failed for {name}: {result.stderr[:200]}")
        return False
    return True


async def main() -> None:
    print(f"\n{'═' * 60}")
    print(f"  🤖 AI CODING AGENT — SCHEDULED SCAN")
    print(f"  Mode: {SCAN_MODE}")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'═' * 60}")

    # Validate required env vars
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ SUPABASE_URL and SUPABASE_KEY are required")
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        print("❌ ANTHROPIC_API_KEY is required")
        sys.exit(1)

    # Check settings from Supabase
    print("\n📋 Checking settings from Supabase...")
    settings = await get_settings()

    if not settings:
        print("❌ Could not fetch settings from Supabase")
        sys.exit(1)

    weekly_enabled = settings.get("weekly_scan_enabled", True)
    configured_repos = settings.get("scan_repos", list(REPO_CONFIG.keys()))

    print(f"  Weekly scan enabled: {weekly_enabled}")
    print(f"  Configured repos: {configured_repos}")

    # Check if scan is enabled (unless forced)
    if not weekly_enabled and not FORCE_SCAN:
        print("\n⏸️  Weekly scan is DISABLED in dashboard settings.")
        print("   Enable it in the dashboard or use force=true to override.")
        print("   Exiting without scanning.")
        sys.exit(0)

    if FORCE_SCAN:
        print("  ⚡ Force scan — ignoring enabled/disabled setting")

    # Determine which repos to scan
    if OVERRIDE_REPOS:
        repos_to_scan = [r.strip() for r in OVERRIDE_REPOS.split(",") if r.strip()]
        print(f"\n  Override repos: {repos_to_scan}")
    else:
        repos_to_scan = [r for r in configured_repos if r in REPO_CONFIG]
        print(f"\n  Scanning {len(repos_to_scan)} configured repos")

    if not repos_to_scan:
        print("⚠️  No repos to scan!")
        sys.exit(0)

    # Clone and scan each repo
    results = []
    start_time = time.time()

    for repo_name in repos_to_scan:
        if repo_name not in REPO_CONFIG:
            print(f"\n  ⚠️  Unknown repo: {repo_name} — skipping")
            continue

        repo_path, language, clone_url = REPO_CONFIG[repo_name]

        # Clone repo
        print(f"\n  📥 Cloning {repo_name}...")
        cloned = await clone_repo(repo_name, clone_url, repo_path)
        if not cloned:
            results.append({"repo": repo_name, "status": "clone_failed"})
            continue

        # Scan
        scan_fn = SCAN_FUNCTIONS.get(language)
        if not scan_fn:
            print(f"  ⚠️  No scanner for language: {language}")
            continue

        try:
            await scan_fn(repo_path, repo_name)
            results.append({"repo": repo_name, "status": "success", "language": language})
        except Exception as e:
            print(f"  ❌ Scan failed for {repo_name}: {e}")
            results.append({"repo": repo_name, "status": "error", "error": str(e)})

        # Small delay between scans to avoid rate limiting
        await asyncio.sleep(3)

    # Update timestamps in Supabase
    await update_scan_timestamps()

    # Summary
    elapsed = round(time.time() - start_time, 1)
    print(f"\n{'═' * 60}")
    print(f"  ✅ SCAN COMPLETE ({elapsed}s)")
    print(f"{'═' * 60}")
    for r in results:
        icon = "✅" if r["status"] == "success" else "❌"
        print(f"  {icon} {r['repo']}: {r['status']}")

    failed = [r for r in results if r["status"] != "success"]
    if failed:
        print(f"\n  ⚠️  {len(failed)} scan(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
