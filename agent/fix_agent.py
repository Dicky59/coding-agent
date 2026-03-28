"""
Fix Agent — Phase 4
Reads bug findings, generates targeted fixes using Claude,
asks for confirmation, then commits fixes to a new branch and opens a PR.

Usage:
    python fix_agent.py <repo_path> --findings bugs.json
    python fix_agent.py C:/Users/dicky/projects/DailyPulse --findings bugs.json
"""

import asyncio
import time
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
load_dotenv()

from anthropic import Anthropic
from pydantic import BaseModel


# ─── Data models ─────────────────────────────────────────────────────────────

class BugFinding(BaseModel):
    file: str
    line: int
    severity: str
    category: str
    title: str
    description: str
    suggested_fix: str


class ProposedFix(BaseModel):
    finding: BugFinding
    original_line: str
    fixed_line: str
    explanation: str
    confidence: str   # high / medium / low
    applied: bool = False


# ─── Claude fix generator ─────────────────────────────────────────────────────

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

FIX_SYSTEM_PROMPT = """You are an expert Kotlin/Android developer.
Your job is to generate minimal, targeted fixes for specific code issues.

Rules:
- Fix ONLY the specific line or lines mentioned
- Do NOT rewrite or restructure surrounding code
- Do NOT change variable names, logic, or formatting elsewhere
- The fix must be syntactically valid Kotlin
- If the fix requires importing a new class, mention it in explanation
- If you are not confident about the fix, say so clearly

Respond in this exact JSON format:
{
  "fixed_line": "the corrected line of code",
  "explanation": "brief explanation of what was changed and why",
  "confidence": "high|medium|low",
  "requires_import": "fully.qualified.ClassName or null",
  "uncertain": false
}

If you cannot safely fix it, respond with:
{
  "fixed_line": null,
  "explanation": "why this cannot be auto-fixed",
  "confidence": "low",
  "requires_import": null,
  "uncertain": true
}
"""


async def generate_fix(finding: BugFinding, file_content: str) -> dict | None:
    """Ask Claude to generate a targeted fix for a single finding."""
    await asyncio.sleep(3)  # Avoid rate limiting
    lines = file_content.splitlines()
    line_idx = finding.line - 1

    if line_idx < 0 or line_idx >= len(lines):
        return None

    original_line = lines[line_idx]

    # Provide context: 5 lines before and after
    start = max(0, line_idx - 5)
    end = min(len(lines), line_idx + 6)
    context_lines = []
    for i, l in enumerate(lines[start:end], start=start):
        marker = " >>> " if i == line_idx else "     "
        context_lines.append(f"{i+1:4d}{marker}{l}")
    context = "\n".join(context_lines)

    prompt = f"""Fix this Kotlin issue:

ISSUE: {finding.title}
SEVERITY: {finding.severity}
CATEGORY: {finding.category}
DESCRIPTION: {finding.description}
SUGGESTED FIX: {finding.suggested_fix}

FILE: {Path(finding.file).name}
LINE {finding.line} (marked with >>>):

{context}

The exact line to fix:
{original_line}

Generate the fix JSON now."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=FIX_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        print(f"    🔎 Raw response: {text[:200]}")
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())
        result["original_line"] = original_line
        return result
    except Exception as e:
        print(f"    ⚠️  Claude error: {e}")
        return None


# ─── Interactive confirmation ─────────────────────────────────────────────────

def show_diff(finding: BugFinding, original: str, fixed: str, explanation: str) -> None:
    """Show a colored diff of the proposed fix."""
    print(f"\n{'─' * 60}")
    print(f"  📄 {Path(finding.file).name}:{finding.line}")
    print(f"  🏷️  [{finding.severity.upper()}] {finding.title}")
    print(f"\n  ❌ Original:")
    print(f"     {original.strip()}")
    print(f"\n  ✅ Fixed:")
    print(f"     {fixed.strip()}")
    print(f"\n  💬 {explanation}")
    print(f"{'─' * 60}")


def ask_confirmation(finding: BugFinding, fix: dict) -> str:
    """
    Ask the user whether to apply the fix.
    Returns: 'y' (yes), 'n' (no/skip), 'q' (quit)
    """
    confidence = fix.get("confidence", "low")
    uncertain = fix.get("uncertain", False)

    if uncertain:
        print(f"\n  ⚠️  LOW CONFIDENCE — Claude is uncertain about this fix")

    conf_icon = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(confidence, "⚪")
    print(f"  {conf_icon} Confidence: {confidence.upper()}")

    requires_import = fix.get("requires_import")
    if requires_import:
        print(f"  📦 Requires import: {requires_import}")

    while True:
        answer = input("\n  Apply this fix? [y]es / [n]o (skip) / [q]uit: ").strip().lower()
        if answer in ("y", "yes"):
            return "y"
        elif answer in ("n", "no", "s", "skip", ""):
            return "n"
        elif answer in ("q", "quit"):
            return "q"
        print("  Please enter y, n, or q")


# ─── Fix applier ──────────────────────────────────────────────────────────────

def apply_fix(file_path: str, line_number: int, fixed_line: str, requires_import: str | None) -> bool:
    """Apply a fix to a file by replacing the specific line."""
    path = Path(file_path)
    try:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        line_idx = line_number - 1

        if line_idx < 0 or line_idx >= len(lines):
            print(f"    ❌ Line {line_number} out of range")
            return False

        # Preserve original indentation
        original = lines[line_idx]
        indent = len(original) - len(original.lstrip())
        indentation = original[:indent]

        # Apply the fix with preserved indentation
        fixed = indentation + fixed_line.strip()
        if not fixed.endswith("\n"):
            fixed += "\n"
        lines[line_idx] = fixed

        # Add import if needed
        if requires_import:
            import_line = f"import {requires_import}\n"
            # Find the last import line and insert after it
            last_import = 0
            for i, line in enumerate(lines):
                if line.startswith("import "):
                    last_import = i
            if import_line not in lines:
                lines.insert(last_import + 1, import_line)
                print(f"    📦 Added import: {requires_import}")

        path.write_text("".join(lines), encoding="utf-8")
        return True

    except Exception as e:
        print(f"    ❌ Error applying fix: {e}")
        return False


# ─── Git operations ───────────────────────────────────────────────────────────

def run_git(args: list[str], cwd: str) -> tuple[bool, str]:
    """Run a git command and return (success, output)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)


def create_fix_branch(repo_path: str, branch_name: str) -> bool:
    """Create and checkout a new branch for fixes."""
    success, output = run_git(["checkout", "-b", branch_name], repo_path)
    if not success:
        # Branch might already exist
        success, output = run_git(["checkout", branch_name], repo_path)
    return success


def commit_fixes(repo_path: str, files: list[str], message: str) -> bool:
    """Stage and commit fixed files."""
    for file_path in files:
        rel_path = str(Path(file_path).relative_to(repo_path))
        run_git(["add", rel_path], repo_path)

    success, output = run_git(["commit", "-m", message], repo_path)
    return success


def push_branch(repo_path: str, branch_name: str) -> bool:
    """Push the fix branch to origin."""
    success, output = run_git(
        ["push", "--set-upstream", "origin", branch_name], repo_path
    )
    if not success:
        print(f"    ⚠️  Push output: {output}")
    return success


# ─── GitHub PR creation ───────────────────────────────────────────────────────

GITHUB_API = "https://api.github.com"


def github_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not set in .env")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def get_default_branch(owner: str, repo: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}",
            headers=github_headers(),
        )
        resp.raise_for_status()
        return resp.json().get("default_branch", "main")


async def create_pr(
    owner: str,
    repo: str,
    branch: str,
    title: str,
    body: str,
    base: str,
) -> str:
    """Create a PR and return its URL."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            headers=github_headers(),
            json={
                "title": title,
                "body": body,
                "head": branch,
                "base": base,
            },
        )
        resp.raise_for_status()
        return resp.json()["html_url"]


def format_pr_body(fixes: list[ProposedFix]) -> str:
    lines = [
        "## 🤖 AI Auto-Fix Report",
        "",
        f"This PR was automatically generated by the AI Coding Agent.",
        f"Applied **{len(fixes)} fix(es)** across {len(set(f.finding.file for f in fixes))} file(s).",
        "",
        "### Applied Fixes",
        "",
    ]
    for fix in fixes:
        sev_icon = {
            "critical": "🔴", "high": "🟠",
            "medium": "🟡", "low": "🟢"
        }.get(fix.finding.severity, "⚪")
        lines += [
            f"#### {sev_icon} {fix.finding.title}",
            f"- **File:** `{Path(fix.finding.file).name}:{fix.finding.line}`",
            f"- **Category:** {fix.finding.category}",
            f"- **Change:** {fix.explanation}",
            "",
            "```kotlin",
            f"// Before:",
            f"{fix.original_line.strip()}",
            f"// After:",
            f"{fix.fixed_line.strip()}",
            "```",
            "",
        ]
    lines += [
        "---",
        "*Generated by [AI Coding Agent](https://github.com/Dicky59/coding-agent) · Phase 4*",
        "",
        "> ⚠️ Please review all changes carefully before merging.",
    ]
    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run_fix_agent(repo_path: str, findings_file: str) -> None:
    print(f"\n🔧 Fix Agent starting...")
    print(f"📁 Repo: {repo_path}")
    print(f"📋 Findings: {findings_file}")

    # Load findings
    findings_path = Path(findings_file)
    if not findings_path.exists():
        print(f"❌ Findings file not found: {findings_file}")
        print("   Run bug_agent.py first to generate bugs.json")
        sys.exit(1)

    data = json.loads(findings_path.read_text(encoding="utf-8"))
    all_findings = [BugFinding(**f) for f in data.get("findings", [])]

    # Filter to fixable severities
    fixable = [
        f for f in all_findings
        if f.severity in ("critical", "high", "medium")
        and f.category in ("bug", "security", "performance", "pattern")
    ]

    print(f"\n📊 Findings loaded: {len(all_findings)} total, {len(fixable)} fixable")

    if not fixable:
        print("✅ No fixable findings!")
        return

    # Show summary
    print(f"\n{'═' * 60}")
    print(f"  FINDINGS TO FIX")
    print(f"{'═' * 60}")
    for f in fixable:
        sev_icon = {
            "critical": "🔴", "high": "🟠",
            "medium": "🟡", "low": "🟢"
        }.get(f.severity, "⚪")
        print(f"  {sev_icon} [{f.severity.upper()}] {Path(f.file).name}:{f.line} — {f.title}")
    print(f"{'═' * 60}")
    print(f"\n  Will now generate fixes one by one and ask for confirmation.")
    input("  Press Enter to start...\n")

    # Generate and confirm fixes
    approved_fixes: list[ProposedFix] = []
    skipped = 0

    for i, finding in enumerate(fixable):
        print(f"\n[{i+1}/{len(fixable)}] Generating fix for: {finding.title}")

        # Read current file content (may have been modified by previous fixes)
        file_path = Path(finding.file)
        if not file_path.exists():
            print(f"  ⚠️  File not found: {finding.file}")
            skipped += 1
            continue

        content = file_path.read_text(encoding="utf-8")

        # Generate fix
        print(f"  🤖 Asking Claude...")
        fix = await generate_fix(finding, content)

        if not fix or fix.get("fixed_line") is None:
            print(f"  ⚠️  Could not generate fix — skipping")
            skipped += 1
            continue

        # Show diff and ask for confirmation
        show_diff(
            finding,
            fix["original_line"],
            fix["fixed_line"],
            fix.get("explanation", ""),
        )

        answer = ask_confirmation(finding, fix)

        if answer == "q":
            print("\n  Quitting fix session...")
            break
        elif answer == "n":
            print("  ⏭️  Skipped")
            skipped += 1
            continue
        else:
            # Apply the fix immediately
            success = apply_fix(
                finding.file,
                finding.line,
                fix["fixed_line"],
                fix.get("requires_import"),
            )
            if success:
                print("  ✅ Fix applied!")
                approved_fixes.append(ProposedFix(
                    finding=finding,
                    original_line=fix["original_line"],
                    fixed_line=fix["fixed_line"],
                    explanation=fix.get("explanation", ""),
                    confidence=fix.get("confidence", "medium"),
                    applied=True,
                ))
            else:
                print("  ❌ Failed to apply fix")
                skipped += 1

    # Summary
    print(f"\n{'═' * 60}")
    print(f"  FIX SESSION COMPLETE")
    print(f"{'═' * 60}")
    print(f"  Applied: {len(approved_fixes)} fixes")
    print(f"  Skipped: {skipped}")
    print(f"{'═' * 60}")

    if not approved_fixes:
        print("\n  No fixes applied — nothing to commit.")
        return

    # Ask about committing
    print(f"\n  Ready to commit {len(approved_fixes)} fix(es) and open a PR.")
    answer = input("  Commit and push? [y]es / [n]o: ").strip().lower()

    if answer not in ("y", "yes"):
        print("  Changes left in working directory — not committed.")
        return

    # Get repo owner/name from git remote
    success, remote_url = run_git(
        ["remote", "get-url", "origin"], repo_path
    )
    owner, repo_name = "", ""
    if success and remote_url:
        # Parse: https://github.com/owner/repo.git or git@github.com:owner/repo.git
        url = remote_url.strip()
        if "github.com" in url:
            parts = url.replace("git@github.com:", "").replace("https://github.com/", "")
            parts = parts.replace(".git", "").strip().split("/")
            if len(parts) >= 2:
                owner, repo_name = parts[0], parts[1]

    # Create fix branch
    branch_name = f"fix/ai-suggested-fixes-{int(time.time())}"
    print(f"\n  Creating branch: {branch_name}")
    success = create_fix_branch(repo_path, branch_name)
    if not success:
        print(f"  ❌ Could not create branch {branch_name}")
        return

    # Commit
    fixed_files = list(set(f.finding.file for f in approved_fixes))
    commit_msg = (
        f"fix: AI suggested fixes ({len(approved_fixes)} issues)\n\n"
        + "\n".join(f"- {f.finding.title} in {Path(f.finding.file).name}:{f.finding.line}"
                    for f in approved_fixes)
    )
    print(f"  Committing {len(fixed_files)} file(s)...")
    success = commit_fixes(repo_path, fixed_files, commit_msg)
    if not success:
        print("  ❌ Commit failed")
        return
    print("  ✅ Committed!")

    # Push
    print(f"  Pushing to origin/{branch_name}...")
    success = push_branch(repo_path, branch_name)
    if not success:
        print("  ❌ Push failed — check your GITHUB_TOKEN permissions")
        return
    print("  ✅ Pushed!")

    # Open PR
    if owner and repo_name:
        print(f"  Opening PR on {owner}/{repo_name}...")
        try:
            base = await get_default_branch(owner, repo_name)
            pr_url = await create_pr(
                owner=owner,
                repo=repo_name,
                branch=branch_name,
                title=f"fix: AI suggested fixes ({len(approved_fixes)} issues)",
                body=format_pr_body(approved_fixes),
                base=base,
            )
            print(f"  ✅ PR opened: {pr_url}")
        except Exception as e:
            print(f"  ⚠️  Could not open PR automatically: {e}")
            print(f"  Open it manually at: https://github.com/{owner}/{repo_name}/compare/{branch_name}")
    else:
        print("  ⚠️  Could not detect GitHub repo — push manually and open PR")

    print(f"\n{'═' * 60}")
    print(f"  ✅ PHASE 4 COMPLETE")
    print(f"{'═' * 60}\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fix_agent.py <repo_path> --findings bugs.json")
        print("Example: python fix_agent.py C:/Users/dicky/projects/DailyPulse --findings bugs.json")
        sys.exit(1)

    repo = sys.argv[1]
    findings_file = "bugs.json"

    if "--findings" in sys.argv:
        idx = sys.argv.index("--findings")
        if idx + 1 < len(sys.argv):
            findings_file = sys.argv[idx + 1]

    asyncio.run(run_fix_agent(repo, findings_file))
