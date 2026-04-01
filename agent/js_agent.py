"""
JavaScript Bug Scanner
Scans JavaScript/JSX repositories using specialized tools.

Usage:
    python js_agent.py <repo_path>
    python js_agent.py C:/Users/dicky/projects/next-dicky
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


# ─── Data models ─────────────────────────────────────────────────────────────

class JSFinding(BaseModel):
    file: str
    line: int
    severity: str
    category: str
    title: str
    description: str
    suggested_fix: str


class JSReport(BaseModel):
    repo_path: str
    total_files_scanned: int
    total_findings: int
    critical: int
    high: int
    medium: int
    low: int
    findings: list[JSFinding]
    ai_summary: str = ""


# ─── MCP client ──────────────────────────────────────────────────────────────

def create_mcp_client() -> MultiServerMCPClient:
    server_path = Path(__file__).parent.parent / "mcp-server" / "server_javascript.py"
    return MultiServerMCPClient(
        {
            "javascript-analyzer": {
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
    except Exception:
        return {}


# ─── Scanner ──────────────────────────────────────────────────────────────────

async def scan_repository(repo_path: str) -> tuple[list[JSFinding], int]:
    mcp_client = create_mcp_client()
    tools = await mcp_client.get_tools()
    print(f"✅ Tools loaded: {[t.name for t in tools]}")

    print("\n📂 Listing JavaScript files...")
    files_result = await call_tool(tools, "list_js_files", {
        "repo_path": repo_path,
        "file_type": "all",
        "include_tests": False,
    })

    js_files = files_result.get("files", [])
    print(f"   Found {len(js_files)} JavaScript files")

    if not js_files:
        print("   No JavaScript files found!")
        return [], 0

    all_findings: list[JSFinding] = []
    analysis_tools = [
        "analyze_js_bugs",
        "analyze_js_security",
        "analyze_js_patterns",
        "analyze_nextjs_js",
        "analyze_react_js",
    ]

    for i, file_info in enumerate(js_files):
        file_path = str(Path(repo_path) / file_info["path"])
        file_name = file_info["name"]
        component_type = file_info.get("component_type", "")
        has_jsx = file_info.get("has_jsx", False)

        jsx_tag = " [jsx]" if has_jsx else ""
        print(f"\n  [{i+1}/{len(js_files)}] 🔍 {file_name} ({component_type}{jsx_tag})")

        file_findings = []
        for tool_name in analysis_tools:
            result = await call_tool(tools, tool_name, {
                "file_path": file_path,
                "repo_path": repo_path,
            })
            findings = result.get("findings", [])
            if findings:
                print(f"    ⚡ {tool_name}: {len(findings)} findings")
            for f in findings:
                file_findings.append(JSFinding(
                    file=file_info["path"],
                    line=f.get("line", 0),
                    severity=f.get("severity", "low"),
                    category=f.get("category", "bug"),
                    title=f.get("title", ""),
                    description=f.get("description", ""),
                    suggested_fix=f.get("suggested_fix", ""),
                ))

        all_findings.extend(file_findings)

    return all_findings, len(js_files)


# ─── AI Summary ───────────────────────────────────────────────────────────────

async def generate_ai_summary(findings: list[JSFinding], repo_path: str) -> str:
    if not findings:
        return "No issues found in the repository."
    try:
        llm = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=os.environ["ANTHROPIC_API_KEY"],
            max_tokens=1024,
        )
        by_severity = {"critical": [], "high": [], "medium": [], "low": []}
        for f in findings:
            by_severity.get(f.severity, []).append(f)

        summary_text = f"JavaScript repo: {repo_path}\nTotal: {len(findings)} findings\n\n"
        for sev, items in by_severity.items():
            if items:
                summary_text += f"{sev.upper()} ({len(items)}):\n"
                for f in items[:5]:
                    summary_text += (
                        f"  - [{f.category}] {f.title} "
                        f"in {Path(f.file).name}:{f.line}\n"
                    )
                if len(items) > 5:
                    summary_text += f"  ... and {len(items) - 5} more\n"
                summary_text += "\n"

        response = llm.invoke([
            SystemMessage(content=(
                "You are an expert JavaScript/Node.js/React developer. "
                "Given these code scan results, provide a concise executive summary "
                "highlighting the most critical issues and recommended priorities. "
                "Be specific about JavaScript gotchas, security risks, and "
                "Next.js/React best practices. Max 250 words."
            )),
            HumanMessage(content=summary_text),
        ])
        return response.content
    except Exception as e:
        return f"AI summary unavailable: {e}"


# ─── Report ───────────────────────────────────────────────────────────────────

def build_report(repo_path, findings, files_scanned, ai_summary) -> JSReport:
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: severity_order.get(f.severity, 4))
    return JSReport(
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


def print_report(report: JSReport) -> None:
    print("\n" + "═" * 60)
    print("  💛 JAVASCRIPT BUG REPORT")
    print("═" * 60)
    print(f"  Repo:    {report.repo_path}")
    print(f"  Scanned: {report.total_files_scanned} JavaScript files")
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

    categories = {
        "security": [], "bug": [], "pattern": [],
        "nextjs": [], "hooks": [],
    }
    for f in report.findings:
        categories.get(f.category, []).append(f)

    category_labels = {
        "security": "🔒 SECURITY",
        "bug":      "🐛 BUGS",
        "pattern":  "🏗️  PATTERNS",
        "nextjs":   "▲  NEXT.JS",
        "hooks":    "🪝 REACT HOOKS",
    }

    for cat, label in category_labels.items():
        items = categories[cat]
        if not items:
            continue
        print(f"\n  {label} ({len(items)} findings)")
        print("  " + "─" * 50)
        for f in items:
            sev_icon = {
                "critical": "🔴", "high": "🟠",
                "medium": "🟡", "low": "🟢"
            }.get(f.severity, "⚪")
            print(f"\n  {sev_icon} [{f.severity.upper()}] {f.title}")
            print(f"     📄 {Path(f.file).name}:{f.line}")
            print(f"     💬 {f.description}")
            print(f"     ✅ Fix: {f.suggested_fix}")

    print("\n" + "═" * 60)


# ─── Main ─────────────────────────────────────────────────────────────────────

async def scan_repo(repo_path: str) -> JSReport:
    print(f"\n💛 JavaScript Scanner starting...")
    print(f"📁 Repo: {repo_path}")

    findings, files_scanned = await scan_repository(repo_path)
    ai_summary = await generate_ai_summary(findings, repo_path)
    report = build_report(repo_path, findings, files_scanned, ai_summary)
    print_report(report)

    from reporter import generate_report, ReportConfig
    config = ReportConfig(
        repo_path=repo_path,
        repo_name=Path(repo_path).name,
        language="javascript",
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
        print("Usage: python js_agent.py <repo_path>")
        print("Example: python js_agent.py C:/Users/dicky/projects/next-dicky")
        sys.exit(1)

    repo = sys.argv[1]
    asyncio.run(scan_repo(repo))
