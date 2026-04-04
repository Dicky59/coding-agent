"""
Fix Agent — TypeScript/JavaScript
Reads findings from Supabase, generates targeted fixes using Claude,
asks for confirmation, then commits fixes to a new branch and opens a PR.

Usage:
    python fix_agent_ts.py <repo_path>
    python fix_agent_ts.py <repo_path> --report-id <supabase-report-uuid>
    python fix_agent_ts.py <repo_path> --severity high
    python fix_agent_ts.py <repo_path> --category security
    python fix_agent_ts.py <repo_path> --auto              # no prompts, apply all

Examples:
    python fix_agent_ts.py C:/Users/dicky/projects/next-store
    python fix_agent_ts.py C:/Users/dicky/projects/next-dicky --severity high
    python fix_agent_ts.py C:/Users/dicky/projects/next-store --auto
    python fix_agent_ts.py C:/Users/dicky/projects/next-store --category security --auto
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


# ─── Data models ─────────────────────────────────────────────────────────────

class Finding(BaseModel):
    id: str
    file: str
    line: int
    severity: str
    category: str
    title: str
    description: str
    suggested_fix: str
    language: str = "typescript"


class ProposedFix(BaseModel):
    finding: Finding
    original_line: str
    fixed_line: str
    explanation: str
    confidence: str  # high / medium / low
    applied: bool = False


# ─── Findings that cannot be safely auto-fixed at line level ─────────────────

SKIP_TITLES = {
    # Multi-line structural changes needed
    "Component file too large",
    "Async operation without error handling",        # needs try/catch wrapping
    "Async operation without Suspense boundary",     # architectural change
    "Missing key prop in list rendering",            # needs item.id context
    "useEffect missing dependency array",            # needs dep analysis
    "useEffect with async function directly",        # multi-line refactor
    "Server Action without input validation",        # needs schema design
    "Server Action without cache revalidation",      # needs path knowledge
    "Server Action without input validation",        # needs schema design
    "Data fetching in client component with useEffect",  # architectural
    "Missing cleanup in useEffect (potential memory leak)",  # multi-line
    "useMemo/useCallback missing dependency array",  # needs dep analysis
    "Hardcoded URL instead of environment variable", # needs env var name
    "Direct Prisma call in page component",          # refactor needed
    "API route handler without try/catch",           # multi-line
    "API route reading request body without validation",  # needs schema
    "Mutating API route without authentication check",    # needs auth logic
}

# Categories we can reliably auto-fix at line level
AUTO_FIXABLE_CATEGORIES = {
    "typescript",
    "security",
    "bug",
    "pattern",
    "hooks",
    "nextjs",
}


# ─── Supabase ─────────────────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")


def supabase_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


async def fetch_findings(
    repo_name: str,
    report_id: str | None = None,
    severity_filter: str | None = None,
    category_filter: str | None = None,
) -> list[Finding]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ SUPABASE_URL and SUPABASE_KEY must be set in .env")
        sys.exit(1)

    async with httpx.AsyncClient() as client:
        if not report_id:
            resp = await client.get(
                f"{SUPABASE_URL}/rest/v1/reports",
                headers=supabase_headers(),
                params={
                    "repo_name": f"eq.{repo_name}",
                    "select": "id,repo_name,language,scanned_at,total_findings",
                    "order": "scanned_at.desc",
                    "limit": "5",
                },
            )
            if resp.status_code != 200 or not resp.json():
                print(f"❌ No reports found for repo: {repo_name}")
                print("   Run a scan first: python ts_agent.py <repo_path>")
                sys.exit(1)

            reports = resp.json()
            print(f"\n  Found {len(reports)} report(s) for {repo_name}:")
            for i, r in enumerate(reports):
                print(
                    f"  [{i+1}] {r['language'].upper()} — "
                    f"{r['scanned_at'][:10]} — "
                    f"{r['total_findings']} findings"
                )

            if len(reports) == 1:
                chosen = reports[0]
            else:
                while True:
                    try:
                        choice = int(input("\n  Which report to fix? [1]: ").strip() or "1")
                        if 1 <= choice <= len(reports):
                            chosen = reports[choice - 1]
                            break
                    except ValueError:
                        pass
                    print(f"  Enter a number between 1 and {len(reports)}")

            report_id = chosen["id"]
            print(
                f"\n  Using: {chosen['language'].upper()} "
                f"scanned {chosen['scanned_at'][:10]}"
            )

        params: dict = {
            "report_id": f"eq.{report_id}",
            "select": "*",
            "order": "severity.asc",
        }
        if severity_filter:
            params["severity"] = f"eq.{severity_filter}"
        if category_filter:
            params["category"] = f"eq.{category_filter}"

        resp = await client.get(
            f"{SUPABASE_URL}/rest/v1/findings",
            headers=supabase_headers(),
            params=params,
        )
        if resp.status_code != 200:
            print(f"❌ Failed to fetch findings: {resp.status_code}")
            sys.exit(1)

        return [Finding(**f) for f in resp.json()]


# ─── Claude fix generator ─────────────────────────────────────────────────────

claude = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

TS_FIX_SYSTEM_PROMPT = """You are an expert TypeScript/JavaScript/React/Next.js developer.
Generate minimal, targeted fixes for specific code issues.

Rules:
- Fix ONLY the specific line mentioned
- Do NOT rewrite surrounding code
- Preserve indentation and code style
- The fix must be syntactically valid

Common fixes:
- 'any' type → 'unknown' or specific interface
- Non-null assertion (!) → optional chaining (?.) with ?? fallback
- Unsafe 'as' cast → safer alternative
- 'var' → 'const' or 'let'
- '==' → '==='
- '!=' → '!=='
- console.log → set fixed_line to "" (empty string = delete line)
- Array index as key → use item.id or item.slug if visible in context

Respond ONLY with valid JSON, no markdown, no extra text:
{
  "fixed_line": "corrected line of code",
  "explanation": "brief explanation",
  "confidence": "high|medium|low",
  "requires_import": null,
  "uncertain": false
}

Set fixed_line to "" to delete a line (e.g. console.log removal).
Set fixed_line to null if you cannot safely fix in one line."""


async def generate_fix(finding: Finding, file_content: str) -> dict | None:
    lines = file_content.splitlines()
    line_idx = finding.line - 1

    if line_idx < 0 or line_idx >= len(lines):
        return None

    original_line = lines[line_idx]

    start = max(0, line_idx - 5)
    end = min(len(lines), line_idx + 6)
    context_lines = []
    for i, line in enumerate(lines[start:end], start=start):
        marker = " >>> " if i == line_idx else "     "
        context_lines.append(f"{i+1:4d}{marker}{line}")
    context = "\n".join(context_lines)

    lang = finding.language or "typescript"
    prompt = f"""Fix this {lang} issue:

ISSUE: {finding.title}
SEVERITY: {finding.severity}
DESCRIPTION: {finding.description}
SUGGESTED FIX: {finding.suggested_fix}

FILE: {Path(finding.file).name}
LINE {finding.line} (marked with >>>):

{context}

Line to fix:
{original_line}

JSON only, no markdown:"""

    time.sleep(1)
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=512,
            system=TS_FIX_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Strip markdown fences if present
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                if part.startswith("{"):
                    text = part
                    break
        result = json.loads(text.strip())
        result["original_line"] = original_line
        return result
    except Exception as e:
        print(f"    ⚠️  Claude error: {e}")
        return None


# ─── Interactive UI ───────────────────────────────────────────────────────────

def show_diff(finding: Finding, original: str, fixed: str, explanation: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  📄 {Path(finding.file).name}:{finding.line}")
    sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
        finding.severity, "⚪"
    )
    print(f"  {sev_icon} [{finding.severity.upper()}] {finding.title}")
    if fixed == "":
        print(f"\n  🗑️  Remove line:")
        print(f"     {original.strip()}")
    else:
        print(f"\n  ❌ Before:  {original.strip()}")
        print(f"  ✅ After:   {fixed.strip()}")
    print(f"\n  💬 {explanation}")
    print(f"{'─' * 60}")


def ask_confirmation(finding: Finding, fix: dict, apply_all: bool) -> str:
    """Returns: 'y', 'n', 'a' (apply all), 'q' (quit)"""
    confidence = fix.get("confidence", "low")
    uncertain = fix.get("uncertain", False)

    # In apply-all mode skip low confidence
    if apply_all:
        if uncertain or confidence == "low":
            print(f"  ⏭️  Auto-skip (low confidence)")
            return "n"
        return "y"

    if uncertain:
        print(f"\n  ⚠️  LOW CONFIDENCE — Claude is uncertain")

    conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(confidence, "⚪")
    print(f"  {conf_icon} Confidence: {confidence.upper()}")

    requires_import = fix.get("requires_import")
    if requires_import and requires_import not in ("null", "None", ""):
        print(f"  📦 Requires: {requires_import}")

    while True:
        answer = input("\n  [y]es / [n]o / [a]ll remaining / [q]uit: ").strip().lower()
        if answer in ("y", "yes"):
            return "y"
        elif answer in ("n", "no", "s", "skip", ""):
            return "n"
        elif answer in ("a", "all"):
            return "a"
        elif answer in ("q", "quit"):
            return "q"
        print("  Enter y, n, a, or q")


# ─── Fix applier ─────────────────────────────────────────────────────────────

def apply_fix(
    file_path: str,
    line_number: int,
    fixed_line: str,
    requires_import: str | None,
) -> bool:
    path = Path(file_path)
    try:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        line_idx = line_number - 1

        if line_idx < 0 or line_idx >= len(lines):
            print(f"    ❌ Line {line_number} out of range")
            return False

        original = lines[line_idx]

        if fixed_line == "":
            # Delete the line
            lines.pop(line_idx)
        else:
            # Preserve indentation
            indent = len(original) - len(original.lstrip())
            indentation = original[:indent]
            fixed = indentation + fixed_line.strip()
            if not fixed.endswith("\n"):
                fixed += "\n"
            lines[line_idx] = fixed

        # Add import if needed
        if requires_import and requires_import not in ("null", "None", ""):
            import_line = f"{requires_import}\n"
            last_import = 0
            for i, line in enumerate(lines):
                if line.strip().startswith("import "):
                    last_import = i
            if import_line not in lines:
                lines.insert(last_import + 1, import_line)
                print(f"    📦 Added: {requires_import}")

        path.write_text("".join(lines), encoding="utf-8")
        return True

    except Exception as e:
        print(f"    ❌ Error: {e}")
        return False


# ─── Git / GitHub ─────────────────────────────────────────────────────────────

def run_git(args: list[str], cwd: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)


def create_fix_branch(repo_path: str, branch_name: str) -> bool:
    success, _ = run_git(["checkout", "-b", branch_name], repo_path)
    if not success:
        success, _ = run_git(["checkout", branch_name], repo_path)
    return success


def commit_fixes(repo_path: str, files: list[str], message: str) -> bool:
    for fp in files:
        try:
            rel = str(Path(fp).relative_to(repo_path))
        except ValueError:
            rel = fp
        run_git(["add", rel], repo_path)
    ok, _ = run_git(["commit", "-m", message], repo_path)
    return ok


def push_branch(repo_path: str, branch_name: str) -> bool:
    ok, output = run_git(
        ["push", "--set-upstream", "origin", branch_name], repo_path
    )
    if not ok:
        print(f"    ⚠️  {output}")
    return ok


def get_github_remote(repo_path: str) -> tuple[str, str]:
    ok, url = run_git(["remote", "get-url", "origin"], repo_path)
    if not ok or "github.com" not in url:
        return "", ""
    parts = (
        url.strip()
        .replace("git@github.com:", "")
        .replace("https://github.com/", "")
        .replace(".git", "")
        .split("/")
    )
    return (parts[0], parts[1]) if len(parts) >= 2 else ("", "")


GITHUB_API = "https://api.github.com"


def github_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def get_default_branch(owner: str, repo: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}", headers=github_headers()
        )
        resp.raise_for_status()
        return resp.json().get("default_branch", "main")


async def create_pr(
    owner: str, repo: str, branch: str, title: str, body: str, base: str
) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            headers=github_headers(),
            json={"title": title, "body": body, "head": branch, "base": base},
        )
        resp.raise_for_status()
        return resp.json()["html_url"]


def format_pr_body(fixes: list[ProposedFix]) -> str:
    lang = fixes[0].finding.language if fixes else "typescript"
    lines = [
        "## 🤖 AI Auto-Fix Report",
        "",
        f"Applied **{len(fixes)} fix(es)** across "
        f"{len(set(f.finding.file for f in fixes))} file(s).",
        "",
        "### Applied Fixes",
        "",
    ]
    for fix in fixes:
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
            fix.finding.severity, "⚪"
        )
        after = fix.fixed_line.strip() if fix.fixed_line else "(line removed)"
        lines += [
            f"#### {icon} {fix.finding.title}",
            f"- **File:** `{Path(fix.finding.file).name}:{fix.finding.line}`",
            f"- **Change:** {fix.explanation}",
            "",
            f"```{lang}",
            f"// Before: {fix.original_line.strip()}",
            f"// After:  {after}",
            "```",
            "",
        ]
    lines += [
        "---",
        "*Generated by [AI Coding Agent](https://github.com/Dicky59/coding-agent)*",
        "> ⚠️ Review all changes carefully before merging.",
    ]
    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run_fix_agent(
    repo_path: str,
    report_id: str | None = None,
    severity_filter: str | None = None,
    category_filter: str | None = None,
    auto_mode: bool = False,
) -> None:
    repo_name = Path(repo_path).name

    print(f"\n📘 TypeScript/JavaScript Fix Agent")
    print(f"📁 Repo: {repo_path}")
    if auto_mode:
        print(f"⚡ Mode: AUTO (skips low confidence, no prompts)")
    if severity_filter:
        print(f"🔍 Severity: {severity_filter}")
    if category_filter:
        print(f"🔍 Category: {category_filter}")

    print("\n  📋 Loading findings from Supabase...")
    all_findings = await fetch_findings(
        repo_name, report_id, severity_filter, category_filter
    )

    # Filter to auto-fixable
    fixable = [
        f for f in all_findings
        if f.severity in ("critical", "high", "medium")
        and f.category in AUTO_FIXABLE_CATEGORIES
        and f.title not in SKIP_TITLES
    ]

    skipped_types = {f.title for f in all_findings if f.title in SKIP_TITLES}

    print(f"\n📊 {len(all_findings)} total → {len(fixable)} auto-fixable")
    if skipped_types:
        print(f"  ℹ️  Skipping {len(skipped_types)} type(s) that need manual fixes:")
        for t in sorted(skipped_types):
            print(f"    - {t}")

    if not fixable:
        print("\n  ✅ No auto-fixable findings!")
        return

    # Show summary
    print(f"\n{'═' * 60}")
    print(f"  FINDINGS TO FIX ({len(fixable)})")
    print(f"{'═' * 60}")
    for f in fixable:
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
            f.severity, "⚪"
        )
        print(f"  {icon} {Path(f.file).name}:{f.line} — {f.title}")
    print(f"{'═' * 60}")

    if not auto_mode:
        print(f"\n  [y] Apply  [n] Skip  [a] Apply ALL remaining  [q] Quit")
        input("  Press Enter to start...\n")

    approved_fixes: list[ProposedFix] = []
    skipped = 0
    apply_all = auto_mode

    for i, finding in enumerate(fixable):
        print(f"\n[{i+1}/{len(fixable)}] {finding.title}")

        file_path = Path(finding.file)
        if not file_path.is_absolute():
            file_path = Path(repo_path) / finding.file

        if not file_path.exists():
            print(f"  ⚠️  File not found: {file_path}")
            skipped += 1
            continue

        content = file_path.read_text(encoding="utf-8")

        print(f"  🤖 Asking Claude...")
        fix = await generate_fix(finding, content)

        if not fix or fix.get("fixed_line") is None:
            print(f"  ⚠️  No fix generated — skipping")
            skipped += 1
            continue

        original = fix.get("original_line", "")
        proposed = fix.get("fixed_line", "")

        # Skip if no actual change
        if proposed != "" and proposed.strip() == original.strip():
            print(f"  ⏭️  No change — skipping")
            skipped += 1
            continue

        show_diff(finding, original, proposed, fix.get("explanation", ""))

        answer = ask_confirmation(finding, fix, apply_all)

        if answer == "q":
            print("\n  Quitting...")
            break
        elif answer == "a":
            apply_all = True
            answer = "y"

        if answer == "n":
            print("  ⏭️  Skipped")
            skipped += 1
            continue

        success = apply_fix(
            str(file_path),
            finding.line,
            proposed,
            fix.get("requires_import"),
        )
        if success:
            print("  ✅ Applied!")
            approved_fixes.append(ProposedFix(
                finding=finding,
                original_line=original,
                fixed_line=proposed,
                explanation=fix.get("explanation", ""),
                confidence=fix.get("confidence", "medium"),
                applied=True,
            ))
        else:
            print("  ❌ Failed")
            skipped += 1

    # Summary
    print(f"\n{'═' * 60}")
    print(f"  FIX SESSION COMPLETE")
    print(f"  ✅ Applied: {len(approved_fixes)}  ⏭️  Skipped: {skipped}")
    print(f"{'═' * 60}")

    if not approved_fixes:
        print("\n  Nothing to commit.")
        return

    # Commit + PR
    if not auto_mode:
        answer = input(
            f"\n  Commit {len(approved_fixes)} fix(es) and open PR? [y/n]: "
        ).strip().lower()
        if answer not in ("y", "yes"):
            print("  Changes left uncommitted.")
            return

    owner, repo_git = get_github_remote(repo_path)
    branch = f"fix/ai-ts-fixes-{int(time.time())}"

    print(f"\n  Creating branch: {branch}")
    if not create_fix_branch(repo_path, branch):
        print("  ❌ Could not create branch")
        return

    fixed_files = list({str(Path(repo_path) / f.finding.file) for f in approved_fixes})
    msg = (
        f"fix: AI TypeScript/JS fixes ({len(approved_fixes)} issues)\n\n"
        + "\n".join(
            f"- {f.finding.title} — {Path(f.finding.file).name}:{f.finding.line}"
            for f in approved_fixes
        )
    )

    print(f"  Committing {len(fixed_files)} file(s)...")
    if not commit_fixes(repo_path, fixed_files, msg):
        print("  ❌ Commit failed")
        return
    print("  ✅ Committed!")

    print(f"  Pushing...")
    if not push_branch(repo_path, branch):
        print("  ❌ Push failed — check GITHUB_TOKEN")
        return
    print("  ✅ Pushed!")

    if owner and repo_git:
        try:
            base = await get_default_branch(owner, repo_git)
            pr_url = await create_pr(
                owner=owner,
                repo=repo_git,
                branch=branch,
                title=f"fix: AI TypeScript/JS fixes ({len(approved_fixes)} issues)",
                body=format_pr_body(approved_fixes),
                base=base,
            )
            print(f"  ✅ PR: {pr_url}")
        except Exception as e:
            print(f"  ⚠️  PR failed: {e}")
            print(f"  Open: https://github.com/{owner}/{repo_git}/compare/{branch}")
    else:
        print("  ⚠️  Could not detect GitHub remote")

    print(f"\n{'═' * 60}")
    print(f"  ✅ DONE")
    print(f"{'═' * 60}\n")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fix_agent_ts.py <repo_path> [options]")
        print("")
        print("Options:")
        print("  --report-id <uuid>   Use specific Supabase report")
        print("  --severity <level>   Filter: critical, high, medium, low")
        print("  --category <cat>     Filter: typescript, security, hooks, pattern, bug")
        print("  --auto               Apply all fixes without prompts")
        print("")
        print("Examples:")
        print("  python fix_agent_ts.py C:/Users/dicky/projects/next-store")
        print("  python fix_agent_ts.py C:/Users/dicky/projects/next-store --auto")
        print("  python fix_agent_ts.py C:/Users/dicky/projects/next-dicky --severity high")
        print("  python fix_agent_ts.py C:/Users/dicky/projects/next-store --category security --auto")
        sys.exit(1)

    repo = sys.argv[1]
    report_id = None
    severity = None
    category = None
    auto = "--auto" in sys.argv

    for flag, attr in [("--report-id", "report_id"), ("--severity", "severity"), ("--category", "category")]:
        if flag in sys.argv:
            idx = sys.argv.index(flag)
            if idx + 1 < len(sys.argv):
                val = sys.argv[idx + 1]
                if flag == "--report-id":
                    report_id = val
                elif flag == "--severity":
                    severity = val
                elif flag == "--category":
                    category = val

    asyncio.run(run_fix_agent(repo, report_id, severity, category, auto))
