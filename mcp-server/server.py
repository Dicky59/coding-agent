"""
MCP Server — Repository Reader Tools
Phase 1 of the AI Coding Agent

Exposes tools for:
- Listing files in a repository
- Reading file contents
- Getting directory structure
- Semantic code search (via embeddings)
- Basic static analysis (imports, classes, functions)
"""

import ast
import json
import os
import re
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("repo-reader")

# ─── Supported extensions per language ───────────────────────────────────────

LANGUAGE_EXTENSIONS: dict[str, list[str]] = {
    "kotlin":     [".kt", ".kts"],
    "java":       [".java"],
    "typescript": [".ts", ".tsx"],
    "javascript": [".js", ".jsx"],
    "python":     [".py"],
    "css":        [".css", ".scss", ".sass"],
    "xml":        [".xml"],
    "gradle":     [".gradle", ".gradle.kts"],
    "yaml":       [".yml", ".yaml"],
    "json":       [".json"],
    "markdown":   [".md"],
}

ALL_CODE_EXTENSIONS = {ext for exts in LANGUAGE_EXTENSIONS.values() for ext in exts}

IGNORE_DIRS = {
    ".git", "node_modules", "build", "dist", ".gradle", ".idea",
    "__pycache__", ".next", "out", "target", ".android", ".kotlin",
    "gradle", ".DS_Store", "coverage", ".nyc_output",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def is_safe_path(base: str, target: str) -> bool:
    """Prevent path traversal attacks."""
    base_path = Path(base).resolve()
    target_path = Path(target).resolve()
    return target_path.is_relative_to(base_path)


def detect_language(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    for lang, exts in LANGUAGE_EXTENSIONS.items():
        if ext in exts:
            return lang
    return "unknown"


def count_lines(content: str) -> int:
    return len(content.splitlines())


# ─── Tool: list_files ─────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_files",
            description=(
                "Lists all source files in a repository directory. "
                "Filters by language or extension. Ignores build artifacts, "
                "node_modules, .git etc. Returns file paths with metadata."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Absolute path to the repository root",
                    },
                    "languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Filter by language(s): kotlin, java, typescript, "
                            "javascript, python, css, xml, gradle, yaml, json, markdown. "
                            "Empty = all code files."
                        ),
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "Maximum files to return (default 200)",
                        "default": 200,
                    },
                },
                "required": ["repo_path"],
            },
        ),
        Tool(
            name="read_file",
            description=(
                "Reads the full content of a source file. "
                "Returns content with line numbers, language detection, "
                "and basic metadata (size, line count)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the file",
                    },
                    "repo_path": {
                        "type": "string",
                        "description": "Repo root for safety validation",
                    },
                    "include_line_numbers": {
                        "type": "boolean",
                        "description": "Prefix each line with its number (default true)",
                        "default": True,
                    },
                },
                "required": ["file_path", "repo_path"],
            },
        ),
        Tool(
            name="get_repo_structure",
            description=(
                "Returns the full directory tree of a repository as a "
                "formatted string. Great for giving the LLM a map of the "
                "codebase before diving into specific files."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Absolute path to the repository root",
                    },
                    "max_depth": {
                        "type": "integer",
                        "description": "Maximum directory depth to traverse (default 4)",
                        "default": 4,
                    },
                    "show_files": {
                        "type": "boolean",
                        "description": "Include files in tree (default true)",
                        "default": True,
                    },
                },
                "required": ["repo_path"],
            },
        ),
        Tool(
            name="search_code",
            description=(
                "Searches for a pattern across all source files in a repository. "
                "Supports plain text and regex. Returns matching lines with context."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Absolute path to the repository root",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern (plain text or regex)",
                    },
                    "use_regex": {
                        "type": "boolean",
                        "description": "Treat pattern as regex (default false)",
                        "default": False,
                    },
                    "languages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Limit search to specific languages",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "Lines of context around each match (default 3)",
                        "default": 3,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum results to return (default 50)",
                        "default": 50,
                    },
                },
                "required": ["repo_path", "pattern"],
            },
        ),
        Tool(
            name="analyze_file_symbols",
            description=(
                "Extracts symbols (classes, functions, interfaces, imports) from a file. "
                "Works with Kotlin, Java, TypeScript, JavaScript, and Python. "
                "Useful for building a map of what's defined where."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the file",
                    },
                    "repo_path": {
                        "type": "string",
                        "description": "Repo root for safety validation",
                    },
                },
                "required": ["file_path", "repo_path"],
            },
        ),
        Tool(
            name="get_repo_summary",
            description=(
                "Generates a high-level summary of a repository: "
                "language breakdown, file counts, top-level packages/modules, "
                "detected frameworks (Spring, React, etc.)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {
                        "type": "string",
                        "description": "Absolute path to the repository root",
                    },
                },
                "required": ["repo_path"],
            },
        ),
    ]


# ─── Tool implementations ─────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    match name:
        case "list_files":
            return await _list_files(**arguments)
        case "read_file":
            return await _read_file(**arguments)
        case "get_repo_structure":
            return await _get_repo_structure(**arguments)
        case "search_code":
            return await _search_code(**arguments)
        case "analyze_file_symbols":
            return await _analyze_file_symbols(**arguments)
        case "get_repo_summary":
            return await _get_repo_summary(**arguments)
        case _:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _list_files(
    repo_path: str,
    languages: list[str] | None = None,
    max_files: int = 200,
) -> list[TextContent]:
    repo = Path(repo_path)
    if not repo.exists():
        return [TextContent(type="text", text=f"Error: path does not exist: {repo_path}")]

    # Build allowed extensions set
    if languages:
        allowed_exts: set[str] = set()
        for lang in languages:
            allowed_exts.update(LANGUAGE_EXTENSIONS.get(lang.lower(), []))
    else:
        allowed_exts = ALL_CODE_EXTENSIONS

    files: list[dict] = []
    for path in sorted(repo.rglob("*")):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in allowed_exts:
            continue

        rel = path.relative_to(repo)
        try:
            size = path.stat().st_size
            files.append({
                "path": str(rel),
                "language": detect_language(str(path)),
                "size_bytes": size,
                "size_kb": round(size / 1024, 1),
            })
        except OSError:
            continue

        if len(files) >= max_files:
            break

    result = {
        "repo": repo_path,
        "total_files": len(files),
        "truncated": len(files) >= max_files,
        "files": files,
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _read_file(
    file_path: str,
    repo_path: str,
    include_line_numbers: bool = True,
) -> list[TextContent]:
    if not is_safe_path(repo_path, file_path):
        return [TextContent(type="text", text="Error: path traversal attempt blocked")]

    path = Path(file_path)
    if not path.exists():
        return [TextContent(type="text", text=f"Error: file not found: {file_path}")]

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [TextContent(type="text", text=f"Error reading file: {e}")]

    lines = content.splitlines()
    if include_line_numbers:
        numbered = "\n".join(f"{i+1:4d} | {line}" for i, line in enumerate(lines))
    else:
        numbered = content

    meta = {
        "file": file_path,
        "language": detect_language(file_path),
        "lines": len(lines),
        "size_kb": round(path.stat().st_size / 1024, 1),
    }

    output = f"--- FILE METADATA ---\n{json.dumps(meta, indent=2)}\n\n--- CONTENT ---\n{numbered}"
    return [TextContent(type="text", text=output)]


async def _get_repo_structure(
    repo_path: str,
    max_depth: int = 4,
    show_files: bool = True,
) -> list[TextContent]:
    repo = Path(repo_path)
    if not repo.exists():
        return [TextContent(type="text", text=f"Error: path does not exist: {repo_path}")]

    lines: list[str] = [f"📁 {repo.name}/"]

    def _walk(directory: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return

        entries = [e for e in entries if e.name not in IGNORE_DIRS]
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "

            if entry.is_dir():
                lines.append(f"{prefix}{connector}📁 {entry.name}/")
                _walk(entry, prefix + extension, depth + 1)
            elif show_files and entry.suffix.lower() in ALL_CODE_EXTENSIONS:
                lang = detect_language(str(entry))
                lines.append(f"{prefix}{connector}📄 {entry.name} ({lang})")

    _walk(repo, "", 1)
    return [TextContent(type="text", text="\n".join(lines))]


async def _search_code(
    repo_path: str,
    pattern: str,
    use_regex: bool = False,
    languages: list[str] | None = None,
    context_lines: int = 3,
    max_results: int = 50,
) -> list[TextContent]:
    repo = Path(repo_path)

    if languages:
        allowed_exts: set[str] = set()
        for lang in languages:
            allowed_exts.update(LANGUAGE_EXTENSIONS.get(lang.lower(), []))
    else:
        allowed_exts = ALL_CODE_EXTENSIONS

    if use_regex:
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return [TextContent(type="text", text=f"Invalid regex: {e}")]
    else:
        regex = re.compile(re.escape(pattern), re.IGNORECASE)

    results: list[dict] = []

    for path in sorted(repo.rglob("*")):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in allowed_exts:
            continue

        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        for i, line in enumerate(lines):
            if regex.search(line):
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                context = [
                    {"line_no": j + 1, "content": lines[j], "is_match": j == i}
                    for j in range(start, end)
                ]
                results.append({
                    "file": str(path.relative_to(repo)),
                    "match_line": i + 1,
                    "context": context,
                })
                if len(results) >= max_results:
                    break
        if len(results) >= max_results:
            break

    output = {
        "pattern": pattern,
        "total_matches": len(results),
        "truncated": len(results) >= max_results,
        "results": results,
    }
    return [TextContent(type="text", text=json.dumps(output, indent=2))]


async def _analyze_file_symbols(
    file_path: str,
    repo_path: str,
) -> list[TextContent]:
    if not is_safe_path(repo_path, file_path):
        return [TextContent(type="text", text="Error: path traversal attempt blocked")]

    path = Path(file_path)
    if not path.exists():
        return [TextContent(type="text", text=f"Error: file not found: {file_path}")]

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [TextContent(type="text", text=f"Error reading file: {e}")]

    language = detect_language(file_path)
    symbols: dict[str, list] = {
        "classes": [],
        "functions": [],
        "interfaces": [],
        "imports": [],
        "constants": [],
    }

    # Regex-based extraction — works without tree-sitter for Phase 1
    # For deeper AST analysis, swap these for tree-sitter in Phase 2

    if language in ("kotlin", "java"):
        symbols["classes"] = re.findall(
            r"(?:class|object|data class|sealed class|abstract class|enum class)\s+(\w+)", content
        )
        symbols["interfaces"] = re.findall(r"interface\s+(\w+)", content)
        symbols["functions"] = re.findall(r"(?:fun|void|public|private|protected)\s+(\w+)\s*\(", content)
        symbols["imports"] = re.findall(r"^import\s+([\w.]+)", content, re.MULTILINE)

    elif language in ("typescript", "javascript"):
        symbols["classes"] = re.findall(r"class\s+(\w+)", content)
        symbols["interfaces"] = re.findall(r"interface\s+(\w+)", content)
        symbols["functions"] = re.findall(
            r"(?:function\s+(\w+)|const\s+(\w+)\s*=\s*(?:async\s+)?\(|(\w+)\s*:\s*(?:async\s+)?\()",
            content
        )
        # Flatten tuples
        symbols["functions"] = [f for group in symbols["functions"] for f in group if f]
        symbols["imports"] = re.findall(r"from\s+['\"]([^'\"]+)['\"]", content)
        symbols["constants"] = re.findall(r"^(?:export\s+)?const\s+([A-Z_]{2,})\s*=", content, re.MULTILINE)

    elif language == "python":
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    symbols["classes"].append(node.name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols["functions"].append(node.name)
                elif isinstance(node, ast.Import):
                    symbols["imports"].extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        symbols["imports"].append(node.module)
        except SyntaxError:
            symbols["parse_error"] = "Could not parse Python AST"

    result = {
        "file": file_path,
        "language": language,
        "symbols": {k: list(set(v)) for k, v in symbols.items() if v},
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def _get_repo_summary(repo_path: str) -> list[TextContent]:
    repo = Path(repo_path)
    if not repo.exists():
        return [TextContent(type="text", text=f"Error: path does not exist: {repo_path}")]

    lang_counts: dict[str, int] = {}
    lang_sizes: dict[str, int] = {}
    total_files = 0
    total_lines = 0

    for path in repo.rglob("*"):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in ALL_CODE_EXTENSIONS:
            continue

        lang = detect_language(str(path))
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
        size = path.stat().st_size
        lang_sizes[lang] = lang_sizes.get(lang, 0) + size
        total_files += 1

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            total_lines += count_lines(content)
        except OSError:
            pass

    # Detect frameworks
    frameworks: list[str] = []
    all_files_str = " ".join(str(p) for p in repo.rglob("*"))
    content_sample = ""
    for f in list(repo.rglob("*.kt"))[:5] + list(repo.rglob("*.java"))[:5]:
        try:
            content_sample += f.read_text(encoding="utf-8", errors="replace")[:2000]
        except OSError:
            pass

    if (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        frameworks.append("Gradle")
    if "spring" in content_sample.lower() or "springframework" in content_sample.lower():
        frameworks.append("Spring Boot")
    if (repo / "package.json").exists():
        try:
            pkg = json.loads((repo / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "react" in deps:
                frameworks.append("React")
            if "next" in deps:
                frameworks.append("Next.js")
            if "react-native" in deps:
                frameworks.append("React Native")
        except (json.JSONDecodeError, OSError):
            pass

    summary = {
        "repo": repo_path,
        "total_files": total_files,
        "total_lines": total_lines,
        "detected_frameworks": frameworks,
        "language_breakdown": {
            lang: {
                "files": count,
                "size_kb": round(lang_sizes.get(lang, 0) / 1024, 1),
            }
            for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1])
        },
    }
    return [TextContent(type="text", text=json.dumps(summary, indent=2))]


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
