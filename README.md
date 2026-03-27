# AI Coding Agent — Phase 1: Repository Reader

An AI-powered coding agent that analyzes your Kotlin, Java, Spring Boot, React,
and Android codebases using Claude via LangGraph + MCP.

```
┌─────────────────────────────────────┐
│  React/TypeScript Frontend          │  ← Chat UI dashboard
└──────────────┬──────────────────────┘
               │ HTTP
┌──────────────▼──────────────────────┐
│  FastAPI (Python)                   │  ← Agent API
│  LangGraph orchestration            │
└──────────────┬──────────────────────┘
               │ MCP (stdio)
┌──────────────▼──────────────────────┐
│  MCP Server (Python)                │  ← Repository tools
│  list_files, read_file,             │
│  search_code, analyze_symbols...    │
└─────────────────────────────────────┘
```

## MCP Tools (Phase 1)

| Tool | Description |
|---|---|
| `get_repo_summary` | Language breakdown, file counts, detected frameworks |
| `get_repo_structure` | Full directory tree |
| `list_files` | List files by language |
| `read_file` | Read file content with line numbers |
| `search_code` | Regex/text search across codebase |
| `analyze_file_symbols` | Extract classes, functions, imports |

## Setup

### 1. Python environment (agent + MCP server)

```bash
cd agent
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Environment variables

```bash
cp .env.example .env
# Edit .env and add your Anthropic API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

### 3. Start the MCP server test (optional)

```bash
# Test the MCP server directly
cd mcp-server
python server.py
```

### 4. Start the FastAPI backend

```bash
cd agent
uvicorn api:app --reload --port 8000
```

### 5. Start the React frontend

```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

## CLI Usage

You can also use the agent directly from the command line:

```bash
cd agent
python agent.py /path/to/your/repo "What are the main REST endpoints?"
python agent.py /path/to/your/repo "Summarize the architecture"
python agent.py /path/to/your/repo "Find all Spring @Service classes"
python agent.py /path/to/your/repo "List all React components"
```

## Example Questions

**Architecture:**
- "Give me a high-level summary of this codebase"
- "What is the overall architecture of this Spring Boot app?"
- "How is the frontend structured?"

**Code navigation:**
- "What are all the REST API endpoints?"
- "Find all classes that extend ViewModel"
- "Show me where authentication is handled"
- "List all React hooks used in this project"

**Framework-specific:**
- "What Spring Boot dependencies are configured?"
- "Find all Kotlin data classes"
- "Which components use Redux state?"
- "Show me all Android Activities"

## Phase Roadmap

- [x] **Phase 1** — Repository Reader (this)
- [ ] **Phase 2** — Bug Detection Agent (AST analysis + LLM review)
- [ ] **Phase 3** — GitHub PR Integration (post review comments)
- [ ] **Phase 4** — Automated Fix & PR Agent
- [ ] **Phase 5** — Multi-Agent Architecture (specialized agents)

## Project Structure

```
ai-coding-agent/
├── mcp-server/
│   └── server.py          # MCP server with repo tools
├── agent/
│   ├── agent.py           # LangGraph agent
│   ├── api.py             # FastAPI backend
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    └── src/
        └── App.tsx        # React dashboard
```
