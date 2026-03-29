"""
Reporter — Shared reporting module for all AI Coding Agent scanners
Generates:
1. Beautiful self-contained HTML report
2. GitHub Issues for high/critical findings
3. Slack notification with scan summary

Usage:
    from reporter import generate_report, ReportConfig

    config = ReportConfig(
        repo_path="C:/Users/dicky/projects/MyApp",
        repo_name="MyApp",
        language="kotlin",   # kotlin / java / typescript
        output_dir="reports",
    )
    await generate_report(findings, config)
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


# ─── Config ───────────────────────────────────────────────────────────────────

class ReportConfig(BaseModel):
    repo_path: str
    repo_name: str
    language: str = "kotlin"
    output_dir: str = "reports"
    github_owner: str = ""
    github_repo: str = ""
    create_github_issues: bool = True
    send_slack: bool = True
    open_html: bool = False


class Finding(BaseModel):
    file: str
    line: int
    severity: str
    category: str
    title: str
    description: str
    suggested_fix: str


# ─── HTML Report ──────────────────────────────────────────────────────────────

def generate_html_report(
    findings: list[Finding],
    config: ReportConfig,
    ai_summary: str = "",
) -> str:
    """Generate a beautiful self-contained HTML report."""

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    critical = sum(1 for f in findings if f.severity == "critical")
    high = sum(1 for f in findings if f.severity == "high")
    medium = sum(1 for f in findings if f.severity == "medium")
    low = sum(1 for f in findings if f.severity == "low")

    # Build findings rows
    rows = ""
    for f in sorted(findings, key=lambda x: {"critical":0,"high":1,"medium":2,"low":3}.get(x.severity,4)):
        sev_class = f.severity
        cat_icon = {"security":"🔒","bug":"🐛","performance":"⚡","pattern":"🏗️","jpa":"🗄️"}.get(f.category,"📌")
        file_name = Path(f.file).name
        rows += f"""
        <tr class="finding-row" data-severity="{f.severity}" data-category="{f.category}">
            <td><span class="badge {sev_class}">{f.severity.upper()}</span></td>
            <td>{cat_icon} {f.category}</td>
            <td class="title-cell">
                <div class="finding-title">{f.title}</div>
                <div class="finding-detail" style="display:none">
                    <p class="desc">{f.description}</p>
                    <p class="fix">✅ <strong>Fix:</strong> {f.suggested_fix}</p>
                </div>
            </td>
            <td class="file-cell"><code>{file_name}:{f.line}</code></td>
            <td><button class="expand-btn" onclick="toggleDetail(this)">▼ Details</button></td>
        </tr>"""

    ai_section = ""
    if ai_summary:
        ai_section = f"""
        <div class="ai-summary">
            <h2>🧠 AI Analysis</h2>
            <div class="ai-content">{ai_summary.replace(chr(10), '<br>')}</div>
        </div>"""

    lang_icon = {"kotlin":"🤖","java":"☕","typescript":"📘","javascript":"💛"}.get(config.language,"📄")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Code Review Report — {config.repo_name}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Inter', sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; }}

  .header {{
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    border-bottom: 1px solid #334155;
    padding: 32px 40px;
  }}
  .header-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .repo-name {{ font-size: 28px; font-weight: 700; color: #f1f5f9; }}
  .repo-meta {{ font-size: 13px; color: #64748b; margin-top: 4px; }}
  .scan-time {{ font-size: 12px; color: #475569; text-align: right; }}
  .lang-badge {{
    display: inline-block; padding: 4px 12px; border-radius: 20px;
    background: #1e40af; color: #bfdbfe; font-size: 12px; font-weight: 600;
    margin-top: 8px;
  }}

  .summary-cards {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px;
    padding: 24px 40px;
    background: #0f1117;
  }}
  .card {{
    background: #1e293b; border-radius: 12px; padding: 20px 24px;
    border: 1px solid #334155; text-align: center;
    transition: transform 0.2s;
  }}
  .card:hover {{ transform: translateY(-2px); }}
  .card-count {{ font-size: 36px; font-weight: 700; }}
  .card-label {{ font-size: 12px; color: #94a3b8; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .card.critical .card-count {{ color: #ef4444; }}
  .card.high .card-count {{ color: #f97316; }}
  .card.medium .card-count {{ color: #eab308; }}
  .card.low .card-count {{ color: #22c55e; }}

  .main {{ padding: 24px 40px; }}

  .ai-summary {{
    background: #1e293b; border: 1px solid #334155; border-radius: 12px;
    padding: 24px; margin-bottom: 24px;
    border-left: 4px solid #6366f1;
  }}
  .ai-summary h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 12px; color: #a5b4fc; }}
  .ai-content {{ font-size: 14px; line-height: 1.7; color: #cbd5e1; }}

  .controls {{
    display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap;
    align-items: center;
  }}
  .filter-btn {{
    padding: 7px 16px; border-radius: 8px; border: 1px solid #334155;
    background: #1e293b; color: #94a3b8; font-size: 13px; cursor: pointer;
    font-family: 'Inter', sans-serif; transition: all 0.15s;
  }}
  .filter-btn:hover, .filter-btn.active {{
    background: #6366f1; color: #fff; border-color: #6366f1;
  }}
  .search-box {{
    padding: 7px 14px; border-radius: 8px; border: 1px solid #334155;
    background: #1e293b; color: #e2e8f0; font-size: 13px;
    font-family: 'Inter', sans-serif; outline: none; min-width: 220px;
    margin-left: auto;
  }}
  .search-box:focus {{ border-color: #6366f1; }}

  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    padding: 12px 16px; text-align: left; font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.5px; color: #64748b;
    background: #1e293b; border-bottom: 1px solid #334155;
  }}
  .finding-row td {{
    padding: 14px 16px; border-bottom: 1px solid #1e293b;
    vertical-align: top; font-size: 14px;
  }}
  .finding-row:hover td {{ background: #1e293b; }}
  .finding-row.hidden {{ display: none; }}

  .badge {{
    display: inline-block; padding: 3px 10px; border-radius: 6px;
    font-size: 11px; font-weight: 600; letter-spacing: 0.3px;
  }}
  .badge.critical {{ background: #450a0a; color: #fca5a5; }}
  .badge.high {{ background: #431407; color: #fdba74; }}
  .badge.medium {{ background: #422006; color: #fde68a; }}
  .badge.low {{ background: #052e16; color: #86efac; }}

  .finding-title {{ font-weight: 500; color: #e2e8f0; }}
  .finding-detail {{ margin-top: 10px; padding: 12px; background: #0f172a; border-radius: 8px; }}
  .desc {{ color: #94a3b8; font-size: 13px; line-height: 1.6; margin-bottom: 8px; }}
  .fix {{ color: #86efac; font-size: 13px; line-height: 1.6; }}
  .file-cell code {{
    font-family: 'JetBrains Mono', monospace; font-size: 12px;
    color: #7dd3fc; background: #0f172a; padding: 2px 6px; border-radius: 4px;
  }}

  .expand-btn {{
    padding: 4px 10px; border-radius: 6px; border: 1px solid #334155;
    background: transparent; color: #64748b; font-size: 12px; cursor: pointer;
    font-family: 'Inter', sans-serif; transition: all 0.15s; white-space: nowrap;
  }}
  .expand-btn:hover {{ border-color: #6366f1; color: #a5b4fc; }}
  .expand-btn.open {{ color: #6366f1; border-color: #6366f1; }}

  .table-container {{
    background: #1a2234; border: 1px solid #334155; border-radius: 12px; overflow: hidden;
  }}

  .footer {{
    text-align: center; padding: 24px; color: #475569; font-size: 12px;
    border-top: 1px solid #1e293b; margin-top: 40px;
  }}

  .export-btn {{
    padding: 7px 16px; border-radius: 8px; border: 1px solid #334155;
    background: #1e293b; color: #94a3b8; font-size: 13px; cursor: pointer;
    font-family: 'Inter', sans-serif; transition: all 0.15s;
  }}
  .export-btn:hover {{ background: #0f172a; color: #e2e8f0; }}

  .no-findings {{
    text-align: center; padding: 60px; color: #475569; font-size: 16px;
  }}
</style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <div>
      <div class="repo-name">{lang_icon} {config.repo_name}</div>
      <div class="repo-meta">{config.repo_path}</div>
      <div class="lang-badge">{config.language.upper()}</div>
    </div>
    <div class="scan-time">
      🕐 Scanned: {now}<br>
      🤖 AI Coding Agent
    </div>
  </div>
</div>

<div class="summary-cards">
  <div class="card critical">
    <div class="card-count">{critical}</div>
    <div class="card-label">🔴 Critical</div>
  </div>
  <div class="card high">
    <div class="card-count">{high}</div>
    <div class="card-label">🟠 High</div>
  </div>
  <div class="card medium">
    <div class="card-count">{medium}</div>
    <div class="card-label">🟡 Medium</div>
  </div>
  <div class="card low">
    <div class="card-count">{low}</div>
    <div class="card-label">🟢 Low</div>
  </div>
</div>

<div class="main">
  {ai_section}

  <div class="controls">
    <button class="filter-btn active" onclick="filterSeverity('all', this)">All ({len(findings)})</button>
    <button class="filter-btn" onclick="filterSeverity('critical', this)">Critical ({critical})</button>
    <button class="filter-btn" onclick="filterSeverity('high', this)">High ({high})</button>
    <button class="filter-btn" onclick="filterSeverity('medium', this)">Medium ({medium})</button>
    <button class="filter-btn" onclick="filterSeverity('low', this)">Low ({low})</button>
    <button class="export-btn" onclick="exportCSV()">📥 Export CSV</button>
    <input class="search-box" type="text" placeholder="🔍 Search findings..." oninput="searchFindings(this.value)">
  </div>

  <div class="table-container">
    {"<table><thead><tr><th>Severity</th><th>Category</th><th>Finding</th><th>File</th><th></th></tr></thead><tbody>" + rows + "</tbody></table>" if findings else '<div class="no-findings">✅ No issues found!</div>'}
  </div>
</div>

<div class="footer">
  Generated by <strong>AI Coding Agent</strong> · {now} ·
  {len(findings)} findings in {config.repo_name}
</div>

<script>
function toggleDetail(btn) {{
  const row = btn.closest('tr');
  const detail = row.querySelector('.finding-detail');
  const isOpen = detail.style.display !== 'none';
  detail.style.display = isOpen ? 'none' : 'block';
  btn.textContent = isOpen ? '▼ Details' : '▲ Hide';
  btn.classList.toggle('open', !isOpen);
}}

function filterSeverity(severity, btn) {{
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.finding-row').forEach(row => {{
    if (severity === 'all' || row.dataset.severity === severity) {{
      row.classList.remove('hidden');
    }} else {{
      row.classList.add('hidden');
    }}
  }});
}}

function searchFindings(query) {{
  const q = query.toLowerCase();
  document.querySelectorAll('.finding-row').forEach(row => {{
    const text = row.textContent.toLowerCase();
    row.classList.toggle('hidden', q.length > 0 && !text.includes(q));
  }});
}}

function exportCSV() {{
  const rows = [['Severity','Category','Title','File','Line','Description','Fix']];
  document.querySelectorAll('.finding-row').forEach(row => {{
    const cells = row.querySelectorAll('td');
    const sev = cells[0].textContent.trim();
    const cat = cells[1].textContent.trim();
    const title = row.querySelector('.finding-title').textContent.trim();
    const file = cells[3].textContent.trim();
    const desc = row.querySelector('.desc') ? row.querySelector('.desc').textContent.trim() : '';
    const fix = row.querySelector('.fix') ? row.querySelector('.fix').textContent.trim() : '';
    const line = file.includes(':') ? file.split(':')[1] : '';
    rows.push([sev, cat, title, file, line, desc, fix]);
  }});
  const csv = rows.map(r => r.map(c => '"' + c.replace(/"/g,'""') + '"').join(',')).join('\\n');
  const blob = new Blob([csv], {{type: 'text/csv'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = '{config.repo_name}_findings.csv';
  a.click();
}}
</script>
</body>
</html>"""

    return html


# ─── GitHub Issues ────────────────────────────────────────────────────────────

GITHUB_API = "https://api.github.com"


def github_headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def create_github_issues(
    findings: list[Finding],
    config: ReportConfig,
) -> list[str]:
    """Create GitHub Issues for high/critical findings. Returns list of created URLs."""
    if not config.github_owner or not config.github_repo:
        print("  ⚠️  GitHub owner/repo not set — skipping issue creation")
        return []

    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("  ⚠️  GITHUB_TOKEN not set — skipping issue creation")
        return []

    # Only create issues for high and critical findings
    important = [f for f in findings if f.severity in ("critical", "high")]
    if not important:
        print("  ℹ️  No high/critical findings — no GitHub issues created")
        return []

    created_urls = []
    label_map = {
        "security": "security",
        "bug": "bug",
        "performance": "performance",
        "pattern": "code-quality",
        "jpa": "database",
    }
    sev_label = {
        "critical": "priority: critical",
        "high": "priority: high",
    }

    print(f"\n  📋 Creating GitHub Issues for {len(important)} findings...")

    async with httpx.AsyncClient() as client:
        # Ensure labels exist first
        existing_labels = set()
        try:
            resp = await client.get(
                f"{GITHUB_API}/repos/{config.github_owner}/{config.github_repo}/labels",
                headers=github_headers(),
                params={"per_page": 100},
            )
            if resp.status_code == 200:
                existing_labels = {l["name"] for l in resp.json()}
        except Exception:
            pass

        for finding in important:
            file_name = Path(finding.file).name
            cat_icon = {"security":"🔒","bug":"🐛","performance":"⚡","pattern":"🏗️","jpa":"🗄️"}.get(finding.category,"📌")
            sev_icon = {"critical":"🔴","high":"🟠"}.get(finding.severity,"⚠️")

            title = f"{sev_icon} [{finding.severity.upper()}] {finding.title} — {file_name}"
            body = f"""## {cat_icon} {finding.title}

**Severity**: {finding.severity.upper()}
**Category**: {finding.category}
**File**: `{finding.file}:{finding.line}`
**Detected by**: AI Coding Agent

---

### Description
{finding.description}

### Suggested Fix
{finding.suggested_fix}

### Code Location
```
File: {finding.file}
Line: {finding.line}
```

---
*Auto-generated by [AI Coding Agent](https://github.com/Dicky59/coding-agent)*
"""
            labels = []
            cat_label = label_map.get(finding.category)
            if cat_label and cat_label in existing_labels:
                labels.append(cat_label)
            sv_label = sev_label.get(finding.severity)
            if sv_label and sv_label in existing_labels:
                labels.append(sv_label)

            try:
                resp = await client.post(
                    f"{GITHUB_API}/repos/{config.github_owner}/{config.github_repo}/issues",
                    headers=github_headers(),
                    json={
                        "title": title,
                        "body": body,
                        "labels": labels,
                    },
                )
                if resp.status_code == 201:
                    url = resp.json()["html_url"]
                    created_urls.append(url)
                    print(f"    ✅ Issue created: {url}")
                else:
                    print(f"    ⚠️  Failed to create issue: {resp.status_code}")
            except Exception as e:
                print(f"    ⚠️  Error creating issue: {e}")

            await asyncio.sleep(0.5)  # Rate limit protection

    return created_urls


# ─── Slack Notification ───────────────────────────────────────────────────────

async def send_slack_notification(
    findings: list[Finding],
    config: ReportConfig,
    ai_summary: str = "",
    github_issue_urls: list[str] | None = None,
) -> bool:
    """Send a scan summary to Slack via webhook."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook_url:
        print("  ⚠️  SLACK_WEBHOOK_URL not set — skipping Slack notification")
        return False

    critical = sum(1 for f in findings if f.severity == "critical")
    high = sum(1 for f in findings if f.severity == "high")
    medium = sum(1 for f in findings if f.severity == "medium")
    low = sum(1 for f in findings if f.severity == "low")

    # Determine overall status color
    if critical > 0:
        color = "#ef4444"
        status = "🔴 Critical issues found"
    elif high > 0:
        color = "#f97316"
        status = "🟠 High priority issues found"
    elif medium > 0:
        color = "#eab308"
        status = "🟡 Medium priority issues found"
    else:
        color = "#22c55e"
        status = "✅ Clean scan"

    lang_icon = {"kotlin":"🤖","java":"☕","typescript":"📘","javascript":"💛"}.get(config.language,"📄")

    # Build top findings list for Slack
    top_findings_text = ""
    top = [f for f in findings if f.severity in ("critical","high")][:5]
    if top:
        lines = []
        for f in top:
            sev_icon = {"critical":"🔴","high":"🟠"}.get(f.severity,"⚠️")
            file_name = Path(f.file).name
            lines.append(f"• {sev_icon} *{f.title}* — `{file_name}:{f.line}`")
        top_findings_text = "\n".join(lines)

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{lang_icon} AI Code Review: {config.repo_name}",
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{status}* — {len(findings)} total findings",
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"🔴 *Critical:* {critical}"},
                {"type": "mrkdwn", "text": f"🟠 *High:* {high}"},
                {"type": "mrkdwn", "text": f"🟡 *Medium:* {medium}"},
                {"type": "mrkdwn", "text": f"🟢 *Low:* {low}"},
            ]
        },
    ]

    if top_findings_text:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Top Issues:*\n{top_findings_text}",
            }
        })

    if ai_summary:
        # First 300 chars of summary
        short_summary = ai_summary[:300] + "..." if len(ai_summary) > 300 else ai_summary
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*AI Analysis:*\n{short_summary}",
            }
        })

    if github_issue_urls:
        issues_text = "\n".join(f"• <{url}|GitHub Issue>" for url in github_issue_urls[:3])
        if len(github_issue_urls) > 3:
            issues_text += f"\n_...and {len(github_issue_urls) - 3} more_"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*GitHub Issues Created:*\n{issues_text}",
            }
        })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"🤖 AI Coding Agent · {config.repo_path} · {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        }]
    })

    payload = {
        "attachments": [{
            "color": color,
            "blocks": blocks,
        }]
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code == 200:
                print("  ✅ Slack notification sent!")
                return True
            else:
                print(f"  ⚠️  Slack error: {resp.status_code} — {resp.text}")
                return False
    except Exception as e:
        print(f"  ⚠️  Slack error: {e}")
        return False


# ─── Main generate_report ─────────────────────────────────────────────────────

async def generate_report(
    findings: list[dict],
    config: ReportConfig,
    ai_summary: str = "",
) -> dict[str, Any]:
    """
    Main entry point — generates all reports and notifications.
    findings: list of dicts with keys: file, line, severity, category, title,
              description, suggested_fix
    Returns: dict with paths/URLs of generated artifacts
    """
    print(f"\n📊 Generating reports for {config.repo_name}...")

    # Convert dicts to Finding objects
    typed_findings = [Finding(**f) for f in findings]

    # Create output directory
    out_dir = Path(config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── 1. HTML Report ──
    print("  🎨 Generating HTML report...")
    html = generate_html_report(typed_findings, config, ai_summary)
    html_path = out_dir / f"{config.repo_name}_{config.language}_{timestamp}.html"
    html_path.write_text(html, encoding="utf-8")
    results["html_report"] = str(html_path)
    print(f"  ✅ HTML report: {html_path}")

    # ── 2. JSON Report ──
    json_path = out_dir / f"{config.repo_name}_{config.language}_{timestamp}.json"
    json_path.write_text(
        json.dumps({
            "repo_path": config.repo_path,
            "repo_name": config.repo_name,
            "language": config.language,
            "scanned_at": datetime.now().isoformat(),
            "total_findings": len(typed_findings),
            "critical": sum(1 for f in typed_findings if f.severity == "critical"),
            "high": sum(1 for f in typed_findings if f.severity == "high"),
            "medium": sum(1 for f in typed_findings if f.severity == "medium"),
            "low": sum(1 for f in typed_findings if f.severity == "low"),
            "ai_summary": ai_summary,
            "findings": [f.model_dump() for f in typed_findings],
        }, indent=2),
        encoding="utf-8",
    )
    results["json_report"] = str(json_path)
    print(f"  ✅ JSON report: {json_path}")

    # ── 3. GitHub Issues ──
    github_urls = []
    if config.create_github_issues and config.github_owner and config.github_repo:
        github_urls = await create_github_issues(typed_findings, config)
        results["github_issues"] = github_urls

    # ── 4. Slack Notification ──
    if config.send_slack:
        await send_slack_notification(
            typed_findings, config, ai_summary, github_urls
        )

    print(f"\n  📦 Reports saved to: {out_dir}/")
    return results
