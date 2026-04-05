# 🤖 AI Coding Agent

An AI-powered code review platform that automatically scans, analyzes, and fixes issues across multiple programming languages. Built with Claude, LangGraph, MCP, and Next.js.

**Live Dashboard:** [ai-coding-agent-five.vercel.app/](https://ai-coding-agent-five.vercel.app/)

---

## What It Does

```
You open a Pull Request
        ↓
GitHub Actions triggers automatically
        ↓
AI scans changed files for bugs, security issues, performance problems
        ↓
Review comments posted directly to the PR
        ↓
Results saved to Supabase database
        ↓
Dashboard shows trends over time
```

---

## Features

### 🔍 Multi-Language Static Analysis

Scans source code across 5 languages using custom MCP (Model Context Protocol) servers:

| Language                | Detects                                                                                        |
| ----------------------- | ---------------------------------------------------------------------------------------------- |
| 🤖 **Kotlin/Android**   | Force unwraps (!!) · GlobalScope · runBlocking · hardcoded secrets · MVI pattern violations    |
| ☕ **Java/Spring**      | FetchType.EAGER · missing @Index · N+1 queries · missing auth annotations · JPA issues         |
| 📘 **TypeScript/React** | any type · non-null assertions · missing useEffect deps · Server Action validation · XSS risks |
| 💛 **JavaScript**       | Math.random() for secrets · == vs === · prototype pollution · Supabase error handling          |
| 🐍 **Python**           | Mutable defaults · bare except · time.sleep in async · eval/exec · blocking calls              |

### 🔄 Automated PR Review

Every pull request gets an automatic AI review posted as inline comments:

- Scans changed files only
- Posts findings as inline GitHub review comments
- Approves clean PRs, requests changes on high severity issues
- Runs in ~2 minutes

### 🔧 Interactive Fix Agent

Reads findings from the database and generates targeted fixes:

```bash
# Interactive mode — review each fix before applying
python fix_agent_ts.py C:/projects/next-store

# Automatic mode — apply all high-confidence fixes
python fix_agent_ts.py C:/projects/next-store --auto

# Filter by severity or category
python fix_agent_ts.py C:/projects/next-store --severity high --auto
```

### 📊 Web Dashboard

Next.js dashboard deployed on Vercel reading from Supabase:

- **Reports** — all scan results grouped by project
- **Trends** — findings over time with charts
- **Settings** — toggle weekly scans, pick scan day, trigger manual scans

### ⏰ Scheduled Weekly Scans

GitHub Actions workflow runs every Monday at 8am UTC:

- Checks Supabase settings (can be paused from dashboard)
- Clones and scans all configured repos
- Saves results to database automatically

---

## Architecture

```
┌─────────────────────────────────────────────┐
│          Next.js Dashboard (Vercel)          │
│  Reports · Trends · Settings · Run Scan Now  │
└──────────────────┬──────────────────────────┘
                   │ Supabase JS
┌──────────────────▼──────────────────────────┐
│              Supabase Database               │
│         reports · findings · settings        │
└──────────────────▲──────────────────────────┘
                   │ httpx REST API
┌──────────────────┴──────────────────────────┐
│           Python Agent Layer                 │
│  bug_agent · ts_agent · js_agent · py_agent  │
│  fix_agent · fix_agent_ts · multi_agent      │
│  reporter · scheduled_scanner               │
└──────────────────▲──────────────────────────┘
                   │ MCP stdio
┌──────────────────┴──────────────────────────┐
│           MCP Server Layer                   │
│  server.py (Kotlin) · server_java.py         │
│  server_typescript.py · server_javascript.py │
│  server_python.py                            │
└─────────────────────────────────────────────┘
```

---

## Project Structure

```
coding-agent/
├── .github/
│   └── workflows/
│       ├── scheduled-scan.yml     # Weekly automated scans
│       └── (daily-pulse repo)     # PR review workflow
│
├── mcp-server/
│   ├── server.py                  # Kotlin/Android analyzer (10 tools)
│   ├── server_java.py             # Java/Spring analyzer (6 tools)
│   ├── server_typescript.py       # TypeScript/React analyzer (6 tools)
│   ├── server_javascript.py       # JavaScript/JSX analyzer (6 tools)
│   └── server_python.py           # Python analyzer (5 tools)
│
├── agent/
│   ├── agent.py                   # Phase 1 — repo reader (LangGraph)
│   ├── bug_agent.py               # Kotlin bug scanner
│   ├── java_agent.py              # Java/Spring scanner
│   ├── ts_agent.py                # TypeScript/React scanner
│   ├── js_agent.py                # JavaScript scanner
│   ├── py_agent.py                # Python scanner
│   ├── multi_agent.py             # Multi-language pipeline
│   ├── fix_agent.py               # Kotlin interactive fix agent
│   ├── fix_agent_ts.py            # TypeScript/JS fix agent
│   ├── pr_agent.py                # GitHub PR reviewer
│   ├── reporter.py                # HTML/JSON/Supabase reporter
│   ├── scheduled_scanner.py       # GitHub Actions orchestrator
│   └── github_action_runner.py    # Standalone GH Actions scanner
│
└── dashboard/                     # Next.js dashboard (Vercel)
    ├── app/
    │   ├── page.tsx               # Reports home
    │   ├── trends/page.tsx        # Trends charts
    │   ├── settings/page.tsx      # Schedule settings
    │   └── reports/[id]/page.tsx  # Individual report
    └── lib/
        ├── supabase.ts            # Supabase client
        └── utils.ts               # Shared utilities
```

---

## Setup

### Prerequisites

- Python 3.12+ with `uv` package manager
- Node.js 18+
- Git
- Anthropic API key
- GitHub account
- Supabase account (free tier works)

### 1. Clone the repo

```bash
git clone https://github.com/Dicky59/ai-coding-agent
cd ai-coding-agent
```

### 2. Python environment

```bash
cd agent
uv venv
source .venv/Scripts/activate   # Windows Git Bash
# or: source .venv/bin/activate  # Mac/Linux

uv pip install -r requirements.txt
```

### 3. Environment variables

Create `agent/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_KEY=eyJ...
```

### 4. Supabase database

Run in Supabase SQL Editor:

```sql
create table reports (
  id uuid default gen_random_uuid() primary key,
  repo_name text not null,
  repo_path text,
  language text not null,
  scanned_at timestamptz default now(),
  total_findings int default 0,
  critical int default 0,
  high int default 0,
  medium int default 0,
  low int default 0,
  ai_summary text,
  created_at timestamptz default now()
);

create table findings (
  id uuid default gen_random_uuid() primary key,
  report_id uuid references reports(id) on delete cascade,
  file text,
  line int,
  severity text,
  category text,
  title text,
  description text,
  suggested_fix text,
  language text,
  created_at timestamptz default now()
);

create table settings (
  id int primary key default 1,
  weekly_scan_enabled boolean default true,
  scan_day text default 'monday',
  scan_repos text[] default array['DailyPulse', 'next-store'],
  last_scan_at timestamptz,
  next_scan_at timestamptz,
  updated_at timestamptz default now()
);

insert into settings (id) values (1);

create index findings_report_id_idx on findings(report_id);
create index findings_severity_idx on findings(severity);
```

### 5. Dashboard

```bash
cd dashboard
npm install
```

Create `dashboard/.env.local`:

```
NEXT_PUBLIC_SUPABASE_URL=https://xxxx.supabase.co
NEXT_PUBLIC_SUPABASE_KEY=eyJ...
NEXT_PUBLIC_GITHUB_TOKEN=ghp_...
```

```bash
npm run dev
# Open http://localhost:3333
```

---

## Usage

### Scan a project

```bash
cd agent
source .venv/Scripts/activate

# Kotlin/Android
python bug_agent.py C:/projects/my-android-app

# Java/Spring
python java_agent.py C:/projects/my-spring-api

# TypeScript/Next.js
python ts_agent.py C:/projects/my-nextjs-app

# JavaScript
python js_agent.py C:/projects/my-js-project

# Python
python py_agent.py C:/projects/my-python-project

# Multi-language (auto-detects)
python multi_agent.py C:/projects/my-fullstack-app
```

### Fix issues automatically

```bash
# TypeScript/JavaScript — interactive
python fix_agent_ts.py C:/projects/my-nextjs-app

# Fully automatic (no prompts)
python fix_agent_ts.py C:/projects/my-nextjs-app --auto

# Only high severity
python fix_agent_ts.py C:/projects/my-nextjs-app --severity high --auto

# Kotlin — interactive
python fix_agent.py C:/projects/my-android-app --findings bugs.json
```

### Ask questions about a codebase

```bash
python agent.py C:/projects/my-app "What is the overall architecture?"
python agent.py C:/projects/my-app "Find all REST endpoints"
python agent.py C:/projects/my-app "Where is authentication handled?"
```

### GitHub Actions — Automated PR Review

Add to any repo's `.github/workflows/ai-review.yml` — the AI will review every PR automatically. See the [workflow file](.github/workflows/scheduled-scan.yml) for configuration.

---

## GitHub Actions Secrets Required

For the scheduled scan workflow (`coding-agent` repo):

```
ANTHROPIC_API_KEY
SUPABASE_URL
SUPABASE_KEY
```

For the PR review workflow (target repo, e.g. `my-android-app`):

```
ANTHROPIC_API_KEY
```

---

## Tech Stack

| Layer           | Technology                   |
| --------------- | ---------------------------- |
| AI Model        | Claude Sonnet (Anthropic)    |
| Agent Framework | LangGraph + LangChain        |
| Tool Protocol   | MCP (Model Context Protocol) |
| Language        | Python 3.12                  |
| Database        | Supabase (PostgreSQL)        |
| Dashboard       | Next.js 15 + Tailwind CSS    |
| Charts          | Recharts                     |
| Deployment      | Vercel                       |
| CI/CD           | GitHub Actions               |
| Package Manager | uv (Python)                  |

---

## What's Detected

### Security

- Hardcoded API keys and passwords
- `eval()` / `exec()` usage
- SQL injection via string concatenation
- `Math.random()` for cryptographic operations
- Insecure HTTP connections
- `subprocess` with `shell=True`
- NEXT*PUBLIC* prefix on secret env vars

### Bugs

- Force unwrap `!!` in Kotlin
- Non-null assertions `!` in TypeScript
- Missing `useEffect` dependency arrays
- `var` declarations in JavaScript
- Mutable default arguments in Python
- Bare `except:` clauses

### Performance

- `FetchType.EAGER` on JPA collections (N+1 problem)
- Missing database indexes on foreign keys
- `time.sleep()` blocking async event loops
- Synchronous I/O in async functions

### Code Quality

- Functions too long (50+ lines)
- Missing type hints / TypeScript `any`
- `console.log` left in production code
- Array index used as React key
- TODO/FIXME comments

---

## License

MIT — feel free to use, modify, and build on this.

---

_Built as a learning project to explore AI agent development with Claude, LangGraph, and MCP._
