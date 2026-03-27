"""
PR Review Agent — Phase 3
Reviews GitHub Pull Requests by:
1. Fetching the PR diff from GitHub API
2. Running bug scanner on changed Kotlin files only
3. Posting inline comments on exact lines
4. Posting a summary comment
5. Approving or requesting changes based on findings

Usage:
    python pr_agent.py <owner> <repo> <pr_number>
    python pr_agent.py Dicky59 daily-pulse 1
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
load_dotenv()

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel

# ─── GitHub API ───────────────────────────────────────────────────────────────

GITHUB_API = "https://api.github.com"


def github_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN not set in .env file")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def get_pr_info(owner: str, repo: str, pr_number: int) -> dict:
    """Get PR metadata: title, branch, author."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=github_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def get_pr_files(owner: str, repo: str, pr_number: int) -> list[dict]:
    """Get list of files changed in a PR."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/files",
            headers=github_headers(),
            params={"per_page": 100},
        )
        resp.raise_for_status()
        return resp.json()


async def get_file_content(owner: str, repo: str, file_path: str, ref: str) -> str:
    """Download a file's content at a specific git ref (branch/commit)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/contents/{file_path}",
            headers=github_headers(),
            params={"ref": ref},
        )
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        data = resp.json()
        # Content is base64 encoded
        import base64
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")


async def post_review(
    owner: str,
    repo: str,
    pr_number: int,
    commit_sha: str,
    body: str,
    comments: list[dict],
    action: str,  # APPROVE / REQUEST_CHANGES / COMMENT
) -> dict:
    """Post a full PR review with inline comments."""
    async with httpx.AsyncClient() as client:
        payload = {
            "commit_id": commit_sha,
            "body": body,
            "event": action,
            "comments": comments,
        }
        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers=github_headers(),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def post_comment(owner: str, repo: str, pr_number: int, body: str) -> dict:
    """Post a general comment on the PR."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{pr_number}/comments",
            headers=github_headers(),
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json()


# ─── Data models ─────────────────────────────────────────────────────────────

class BugFinding(BaseModel):
    file: str
    line: int
    severity: str
    category: str
    title: str
    description: str
    suggested_fix: str


# ─── MCP scanner (reused from Phase 2) ───────────────────────────────────────

def create_mcp_client() -> MultiServerMCPClient:
    server_path = Path(__file__).parent.parent / "mcp-server" / "server.py"
    return MultiServerMCPClient(
        {
            "repo-reader": {
                "command": "python",
                "args": [str(server_path)],
                "transport": "stdio",
            }
        }
    )


async def call_tool(tools: list, name: str, args: dict) -> dict:
    tool = next((t for t in tools if t.name == name), None)
    if not tool:
        return {}
    try:
        result = await tool.ainvoke(args)
        if isinstance(result, list) and result:
            first = result[0]
            if isinstance(first, dict) and "text" in first:
                return json.loads(first["text"])
            elif hasattr(first, "text"):
                return json.loads(first.text)
        if isinstance(result, str):
            return json.loads(result)
        if isinstance(result, dict):
            return result
        return {}
    except Exception as e:
        return {}


async def scan_file(tools: list, file_path: str, repo_path: str) -> list[BugFinding]:
    """Run all 4 Kotlin analysis tools on a single file."""
    findings = []
    for tool_name in ["analyze_kotlin_bugs", "analyze_kotlin_security",
                      "analyze_kotlin_performance", "analyze_kotlin_patterns"]:
        result = await call_tool(tools, tool_name, {
            "file_path": file_path,
            "repo_path": repo_path,
        })
        for f in result.get("findings", []):
            findings.append(BugFinding(
                file=file_path,
                line=f.get("line", 0),
                severity=f.get("severity", "low"),
                category=f.get("category", "bug"),
                title=f.get("title", ""),
                description=f.get("description", ""),
                suggested_fix=f.get("suggested_fix", ""),
            ))
    return findings


# ─── Diff line mapper ─────────────────────────────────────────────────────────

def get_changed_lines(patch: str) -> set[int]:
    """Parse a GitHub diff patch and return the set of added/changed line numbers."""
    changed = set()
    if not patch:
        return changed

    current_line = 0
    for line in patch.split("\n"):
        if line.startswith("@@"):
            # Parse @@ -old_start,old_count +new_start,new_count @@
            try:
                new_part = line.split("+")[1].split("@@")[0].strip()
                current_line = int(new_part.split(",")[0]) - 1
            except (IndexError, ValueError):
                continue
        elif line.startswith("+") and not line.startswith("+++"):
            current_line += 1
            changed.add(current_line)
        elif not line.startswith("-"):
            current_line += 1

    return changed


def get_diff_position(patch: str, target_line: int) -> int | None:
    """
    Convert a file line number to a GitHub diff position.
    GitHub inline comments require the position in the diff, not the file line number.
    """
    if not patch:
        return None

    position = 0
    current_line = 0

    for line in patch.split("\n"):
        position += 1
        if line.startswith("@@"):
            try:
                new_part = line.split("+")[1].split("@@")[0].strip()
                current_line = int(new_part.split(",")[0]) - 1
            except (IndexError, ValueError):
                continue
        elif line.startswith("+") and not line.startswith("+++"):
            current_line += 1
            if current_line == target_line:
                return position
        elif not line.startswith("-"):
            current_line += 1

    return None


# ─── Comment formatters ───────────────────────────────────────────────────────

def format_inline_comment(finding: BugFinding) -> str:
    sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(
        finding.severity, "⚪"
    )
    cat_icon = {"security": "🔒", "bug": "🐛", "performance": "⚡", "pattern": "🏗️"}.get(
        finding.category, "📌"
    )
    return (
        f"{sev_icon} **[{finding.severity.upper()}]** {cat_icon} {finding.title}\n\n"
        f"{finding.description}\n\n"
        f"**Suggested fix:** {finding.suggested_fix}\n\n"
        f"*Posted by AI Coding Agent*"
    )


def format_summary_comment(
    findings: list[BugFinding],
    files_scanned: int,
    ai_summary: str,
) -> str:
    critical = sum(1 for f in findings if f.severity == "critical")
    high = sum(1 for f in findings if f.severity == "high")
    medium = sum(1 for f in findings if f.severity == "medium")
    low = sum(1 for f in findings if f.severity == "low")

    lines = [
        "## 🤖 AI Code Review Report",
        "",
        f"Scanned **{files_scanned} Kotlin file(s)** changed in this PR.",
        "",
        "### Summary",
        f"| Severity | Count |",
        f"|----------|-------|",
        f"| 🔴 Critical | {critical} |",
        f"| 🟠 High | {high} |",
        f"| 🟡 Medium | {medium} |",
        f"| 🟢 Low | {low} |",
        f"| **Total** | **{len(findings)}** |",
        "",
    ]

    if ai_summary:
        lines += ["### AI Analysis", "", ai_summary, ""]

    if not findings:
        lines += ["### ✅ No issues found!", ""]
    else:
        lines += ["### Findings by Category", ""]
        by_cat: dict[str, list[BugFinding]] = {}
        for f in findings:
            by_cat.setdefault(f.category, []).append(f)

        cat_labels = {
            "security": "🔒 Security",
            "bug": "🐛 Bugs",
            "performance": "⚡ Performance",
            "pattern": "🏗️ Patterns (MVI)",
        }
        for cat, label in cat_labels.items():
            items = by_cat.get(cat, [])
            if not items:
                continue
            lines.append(f"**{label}** ({len(items)})")
            for f in items:
                sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(f.severity, "⚪")
                lines.append(f"- {sev_icon} `{Path(f.file).name}:{f.line}` — {f.title}")
            lines.append("")

    lines += [
        "---",
        "*Generated by [AI Coding Agent](https://github.com/Dicky59/coding-agent) · Phase 3*",
    ]
    return "\n".join(lines)


# ─── AI summary ───────────────────────────────────────────────────────────────

async def generate_ai_summary(findings: list[BugFinding]) -> str:
    if not findings:
        return ""
    try:
        llm = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=os.environ["ANTHROPIC_API_KEY"],
            max_tokens=512,
        )
        summary_text = f"Total findings: {len(findings)}\n"
        for f in findings[:10]:
            summary_text += f"- [{f.severity}] {f.title} in {Path(f.file).name}:{f.line}\n"

        response = llm.invoke([
            SystemMessage(content=(
                "You are an expert Android/Kotlin code reviewer. "
                "Summarize these PR review findings in 3-4 sentences. "
                "Be specific and actionable. Focus on the most important issues."
            )),
            HumanMessage(content=summary_text),
        ])
        return response.content
    except Exception as e:
        return f"*AI summary unavailable: {e}*"


# ─── Main PR review flow ──────────────────────────────────────────────────────

async def review_pr(owner: str, repo: str, pr_number: int) -> None:
    print(f"\n🔍 PR Review Agent starting...")
    print(f"📋 Reviewing: {owner}/{repo} PR #{pr_number}")

    # ── Step 1: Fetch PR info ──
    print("\n📡 Fetching PR info from GitHub...")
    pr_info = await get_pr_info(owner, repo, pr_number)
    pr_title = pr_info["title"]
    commit_sha = pr_info["head"]["sha"]
    branch = pr_info["head"]["ref"]
    print(f"   Title:  {pr_title}")
    print(f"   Branch: {branch}")
    print(f"   Commit: {commit_sha[:8]}")

    # ── Step 2: Get changed files ──
    print("\n📂 Fetching changed files...")
    pr_files = await get_pr_files(owner, repo, pr_number)
    kotlin_files = [
        f for f in pr_files
        if f["filename"].endswith(".kt") and f["status"] != "removed"
    ]
    print(f"   Total changed files: {len(pr_files)}")
    print(f"   Kotlin files to scan: {len(kotlin_files)}")

    if not kotlin_files:
        print("   No Kotlin files changed in this PR — nothing to review!")
        await post_comment(
            owner, repo, pr_number,
            "## 🤖 AI Code Review\n\nNo Kotlin files changed in this PR. Nothing to review! ✅"
        )
        return

    # ── Step 3: Download files and scan ──
    print("\n🔧 Setting up MCP scanner...")
    mcp_client = create_mcp_client()
    tools = await mcp_client.get_tools()
    print(f"   Tools loaded: {len(tools)}")

    all_findings: list[BugFinding] = []
    file_patches: dict[str, str] = {}  # filename → patch for diff position mapping

    # Write files to temp location for scanning
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        for i, file_info in enumerate(kotlin_files):
            filename = file_info["filename"]
            patch = file_info.get("patch", "")
            file_patches[filename] = patch

            print(f"\n  [{i+1}/{len(kotlin_files)}] 🔍 {Path(filename).name}")

            # Download file content at PR branch
            content = await get_file_content(owner, repo, filename, branch)
            if not content:
                print(f"    ⚠️  Could not download file content")
                continue

            # Write to temp file for scanner
            local_path = tmp_path / Path(filename).name
            local_path.write_text(content, encoding="utf-8")

            # Scan the file
            findings = await scan_file(tools, str(local_path), tmp_dir)

            # Only keep findings on changed lines
            changed_lines = get_changed_lines(patch)
            if changed_lines:
                filtered = [f for f in findings if f.line in changed_lines]
                skipped = len(findings) - len(filtered)
                if skipped:
                    print(f"    ℹ️  Filtered {skipped} findings on unchanged lines")
                findings = filtered

            if findings:
                print(f"    ⚡ {len(findings)} findings")
                # Restore original filename for reporting
                for f in findings:
                    f.file = filename
            all_findings.extend(findings)

    # ── Step 4: Generate AI summary ──
    print("\n🤖 Generating AI summary...")
    ai_summary = await generate_ai_summary(all_findings)

    # ── Step 5: Build inline comments for GitHub review ──
    inline_comments = []
    for finding in all_findings:
        patch = file_patches.get(finding.file, "")
        position = get_diff_position(patch, finding.line)
        if position is None:
            continue
        inline_comments.append({
            "path": finding.file,
            "position": position,
            "body": format_inline_comment(finding),
        })

    # ── Step 6: Decide approve or request changes ──
    critical_or_high = sum(1 for f in all_findings if f.severity in ("critical", "high"))
    if not all_findings:
        action = "APPROVE"
        review_body = "✅ No issues found in the changed Kotlin files. Looks good!"
    elif critical_or_high == 0:
        action = "COMMENT"
        review_body = f"Found {len(all_findings)} minor issues (medium/low severity). Consider addressing them but not blocking."
    else:
        action = "REQUEST_CHANGES"
        review_body = f"Found {critical_or_high} high/critical issue(s) that should be addressed before merging."

    # ── Step 7: Post review to GitHub ──
    print(f"\n📤 Posting review to GitHub (action: {action})...")
    print(f"   Inline comments: {len(inline_comments)}")

    try:
        if inline_comments:
            await post_review(
                owner, repo, pr_number,
                commit_sha=commit_sha,
                body=review_body,
                comments=inline_comments,
                action=action,
            )
            print("   ✅ Inline review posted!")
        else:
            # No inline comments — just post summary comment
            action = "COMMENT"

        # Always post summary comment
        summary = format_summary_comment(all_findings, len(kotlin_files), ai_summary)
        await post_comment(owner, repo, pr_number, summary)
        print("   ✅ Summary comment posted!")

    except httpx.HTTPStatusError as e:
        print(f"   ❌ GitHub API error: {e.response.status_code}")
        print(f"   {e.response.text}")
        return

    # ── Step 8: Print local summary ──
    print(f"\n{'═' * 60}")
    print(f"  ✅ PR REVIEW COMPLETE")
    print(f"{'═' * 60}")
    print(f"  PR:      {owner}/{repo} #{pr_number}")
    print(f"  Files:   {len(kotlin_files)} Kotlin files scanned")
    print(f"  Issues:  {len(all_findings)} total findings")
    print(f"  Action:  {action}")
    print(f"  URL:     https://github.com/{owner}/{repo}/pull/{pr_number}")
    print(f"{'═' * 60}\n")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python pr_agent.py <owner> <repo> <pr_number>")
        print("Example: python pr_agent.py Dicky59 daily-pulse 1")
        sys.exit(1)

    owner = sys.argv[1]
    repo = sys.argv[2]
    pr_number = int(sys.argv[3])

    asyncio.run(review_pr(owner, repo, pr_number))
