"""
Bug Detection Agent — Phase 2 (v2)
Smarter approach: Python drives the file scanning directly,
LLM only used for final analysis summary.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel
from reporter import generate_report, ReportConfig


class BugFinding(BaseModel):
    file: str
    line: int
    severity: str
    category: str
    title: str
    description: str
    suggested_fix: str


class BugReport(BaseModel):
    repo_path: str
    total_files_scanned: int
    total_findings: int
    critical: int
    high: int
    medium: int
    low: int
    findings: list[BugFinding]
    ai_summary: str = ""


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
        # Result is a list of dicts with 'text' key
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
        print(f"    ⚠️  Tool {name} error: {e}")
        return {}


async def scan_repository(repo_path: str) -> tuple[list[BugFinding], int]:
    mcp_client = create_mcp_client()
    tools = await mcp_client.get_tools()
    print(f"✅ Tools loaded: {[t.name for t in tools]}")

    print("\n📂 Listing Kotlin files...")
    files_result = await call_tool(tools, "list_files", {
        "repo_path": repo_path,
        "languages": ["kotlin"],
        "max_files": 500,
    })

    kotlin_files = files_result.get("files", [])
    print(f"   Found {len(kotlin_files)} Kotlin files")

    if not kotlin_files:
        print("   No Kotlin files found!")
        return [], 0

    all_findings: list[BugFinding] = []
    analysis_tools = [
        "analyze_kotlin_bugs",
        "analyze_kotlin_security",
        "analyze_kotlin_performance",
        "analyze_kotlin_patterns",
    ]

    for i, file_info in enumerate(kotlin_files):
        file_path = str(Path(repo_path) / file_info["path"])
        file_name = Path(file_path).name
        print(f"\n  [{i+1}/{len(kotlin_files)}] 🔍 {file_name}")

        for tool_name in analysis_tools:
            result = await call_tool(tools, tool_name, {
                "file_path": file_path,
                "repo_path": repo_path,
            })
            findings = result.get("findings", [])
            if findings:
                print(f"    ⚡ {tool_name}: {len(findings)} findings")
            for f in findings:
                all_findings.append(BugFinding(
                    file=file_path,
                    line=f.get("line", 0),
                    severity=f.get("severity", "low"),
                    category=f.get("category", "bug"),
                    title=f.get("title", ""),
                    description=f.get("description", ""),
                    suggested_fix=f.get("suggested_fix", ""),
                ))

    return all_findings, len(kotlin_files)


async def generate_ai_summary(findings: list[BugFinding], repo_path: str) -> str:
    if not findings:
        return "No issues found in the repository."

    llm = ChatAnthropic(
        model="claude-sonnet-4-20250514",
        api_key=os.environ["ANTHROPIC_API_KEY"],
        max_tokens=2048,
    )

    by_severity = {"critical": [], "high": [], "medium": [], "low": []}
    for f in findings:
        by_severity.get(f.severity, []).append(f)

    summary_text = f"Repository: {repo_path}\nTotal findings: {len(findings)}\n\n"
    for sev, items in by_severity.items():
        if items:
            summary_text += f"{sev.upper()} ({len(items)}):\n"
            for f in items[:5]:
                summary_text += f"  - [{f.category}] {f.title} in {Path(f.file).name}:{f.line}\n"
            if len(items) > 5:
                summary_text += f"  ... and {len(items) - 5} more\n"
            summary_text += "\n"

    print("\n🤖 Generating AI summary...")
    try:
        response = llm.invoke([
            SystemMessage(content=(
                "You are an expert Android/Kotlin code reviewer. "
                "Given these bug scan results, provide a concise executive summary "
                "highlighting the most critical issues and recommended priorities. "
                "Be specific and actionable. Max 200 words."
            )),
            HumanMessage(content=summary_text),
        ])
        return response.content
    except Exception as e:
        return f"AI summary unavailable: {e}"


def build_report(repo_path, findings, files_scanned, ai_summary) -> BugReport:
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: severity_order.get(f.severity, 4))
    return BugReport(
        repo_path=repo_path,
        total_files_scanned=files_scanned,
        total_findings=len(findings),
        critical=sum(1 for f in findings if f.severity == "critical"),
        high=sum(1 for f in findings if f.severity == "high"),
        medium=sum(1 for f in findings if f.severity == "medium"),
        low=sum(1 for f in findings if f.severity == "low"),
        findings=findings,
        ai_summary=ai_summary,
    )


def print_report(report: BugReport) -> None:
    print("\n" + "═" * 60)
    print("  🔍 BUG DETECTION REPORT")
    print("═" * 60)
    print(f"  Repo:    {report.repo_path}")
    print(f"  Scanned: {report.total_files_scanned} Kotlin files")
    print(f"  Total:   {report.total_findings} findings")
    print()
    print(f"  🔴 Critical: {report.critical}")
    print(f"  🟠 High:     {report.high}")
    print(f"  🟡 Medium:   {report.medium}")
    print(f"  🟢 Low:      {report.low}")
    print("═" * 60)

    if report.ai_summary:
        print(f"\n  📋 AI SUMMARY\n  {'─' * 50}")
        for line in report.ai_summary.split("\n"):
            print(f"  {line}")

    if not report.findings:
        print("\n  ✅ No issues found!")
        return

    categories = {"security": [], "bug": [], "performance": [], "pattern": []}
    for f in report.findings:
        categories.get(f.category, []).append(f)

    category_labels = {
        "security":    "🔒 SECURITY",
        "bug":         "🐛 BUGS",
        "performance": "⚡ PERFORMANCE",
        "pattern":     "🏗️  PATTERNS (MVI)",
    }

    for cat, label in category_labels.items():
        findings = categories[cat]
        if not findings:
            continue
        print(f"\n  {label} ({len(findings)} findings)")
        print("  " + "─" * 50)
        for f in findings:
            sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(f.severity, "⚪")
            print(f"\n  {sev_icon} [{f.severity.upper()}] {f.title}")
            print(f"     📄 {Path(f.file).name}:{f.line}")
            print(f"     💬 {f.description}")
            print(f"     ✅ Fix: {f.suggested_fix}")

    print("\n" + "═" * 60)


async def scan_repo(repo_path: str, output_file: str | None = None) -> BugReport:
    print(f"\n🔍 Bug Scanner v2 starting...")
    print(f"📁 Repo: {repo_path}")

    findings, files_scanned = await scan_repository(repo_path)
    ai_summary = await generate_ai_summary(findings, repo_path)
    report = build_report(repo_path, findings, files_scanned, ai_summary)
    print_report(report)

    config = ReportConfig(
        repo_path=repo_path,
        repo_name=Path(repo_path).name,
        language="kotlin",
        output_dir="reports",
        create_github_issues=False,
        send_slack=False,
    )
    await generate_report(
        [f.model_dump() for f in report.findings],
        config,
        report.ai_summary,
    )

    return report


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python bug_agent.py <repo_path> [--output bugs.json]")
        sys.exit(1)

    repo = sys.argv[1]
    output = None
    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output = sys.argv[idx + 1]

    asyncio.run(scan_repo(repo, output))