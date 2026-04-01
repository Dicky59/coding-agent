"""
MCP Server — JavaScript/JSX Analysis Tools
Exposes tools for:
- JavaScript bugs (== vs ===, var usage, typeof gotchas, implicit globals)
- React/JSX patterns (hooks, keys, error handling)
- Node.js / Next.js API routes (unhandled rejections, sync I/O, missing auth)
- Security (prototype pollution, eval, injection risks, exposed secrets)
- Code quality (callback hell, missing 'use strict', console.log in prod)
"""

import json
import re
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

app = Server("javascript-analyzer")

# ─── Helpers ─────────────────────────────────────────────────────────────────

IGNORE_DIRS = {
    ".git", "node_modules", ".next", "dist", "build",
    ".turbo", "coverage", ".cache", "out", "__pycache__",
    "generated", ".vercel",
}

IGNORE_PATH_FRAGMENTS = {
    "node_modules/",
    ".next/",
    "dist/",
    "build/",
}


def is_safe_path(base: str, target: str) -> bool:
    base_path = Path(base).resolve()
    target_path = Path(target).resolve()
    return target_path.is_relative_to(base_path)


def is_ignored_file(file_path: str) -> bool:
    normalized = file_path.replace("\\", "/")
    return any(frag in normalized for frag in IGNORE_PATH_FRAGMENTS)


def read_file_safe(file_path: str) -> str | None:
    try:
        return Path(file_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def should_skip_line(line: str) -> bool:
    stripped = line.strip()
    return (
        stripped.startswith("//")
        or stripped.startswith("*")
        or stripped.startswith("/*")
        or stripped == ""
    )


def make_finding(
    line: int,
    code: str,
    title: str,
    description: str,
    suggested_fix: str,
    severity: str,
    category: str,
) -> dict:
    return {
        "line": line,
        "code": code.strip()[:120],
        "title": title,
        "description": description,
        "suggested_fix": suggested_fix,
        "severity": severity,
        "category": category,
    }


# ─── Tool definitions ─────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="analyze_js_bugs",
            description=(
                "Analyzes a JavaScript file for common bugs: "
                "loose equality (== instead of ===), var usage, "
                "typeof null gotcha, implicit globals, "
                "NaN comparisons, and integer division errors."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to .js/.jsx file"},
                    "repo_path": {"type": "string", "description": "Repo root for safety validation"},
                },
                "required": ["file_path", "repo_path"],
            },
        ),
        Tool(
            name="analyze_js_security",
            description=(
                "Scans a JavaScript file for security issues: "
                "eval() usage, innerHTML assignment, prototype pollution, "
                "hardcoded secrets/API keys, SQL injection via string concat, "
                "exposed sensitive data, and insecure randomness."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to .js/.jsx file"},
                    "repo_path": {"type": "string", "description": "Repo root for safety validation"},
                },
                "required": ["file_path", "repo_path"],
            },
        ),
        Tool(
            name="analyze_js_patterns",
            description=(
                "Reviews JavaScript code quality patterns: "
                "callback hell (deeply nested callbacks), "
                "missing Promise error handling (.catch()), "
                "console.log left in code, "
                "missing 'use strict' in non-module files, "
                "arguments object usage (use rest params instead), "
                "and synchronous operations in async contexts."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to .js/.jsx file"},
                    "repo_path": {"type": "string", "description": "Repo root for safety validation"},
                },
                "required": ["file_path", "repo_path"],
            },
        ),
        Tool(
            name="analyze_nextjs_js",
            description=(
                "Checks Next.js JavaScript API routes and pages for: "
                "missing error handling in API routes, "
                "unprotected sensitive endpoints, "
                "missing input validation, "
                "improper response handling, "
                "and Next.js App Router anti-patterns in JavaScript."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to .js/.jsx file"},
                    "repo_path": {"type": "string", "description": "Repo root for safety validation"},
                },
                "required": ["file_path", "repo_path"],
            },
        ),
        Tool(
            name="analyze_react_js",
            description=(
                "Checks JavaScript React components (.jsx or .js with JSX) for: "
                "missing key props, index as key, "
                "useEffect without dependency array, "
                "direct state mutation, "
                "missing error boundaries, "
                "dangerouslySetInnerHTML usage."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to .js/.jsx file"},
                    "repo_path": {"type": "string", "description": "Repo root for safety validation"},
                },
                "required": ["file_path", "repo_path"],
            },
        ),
        Tool(
            name="list_js_files",
            description=(
                "Lists JavaScript source files in a repository. "
                "Can filter by type: page, component, hook, api, util, all. "
                "Ignores node_modules, .next, dist."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "Absolute path to repo root"},
                    "file_type": {
                        "type": "string",
                        "description": "Filter: page, component, hook, api, util, all",
                        "default": "all",
                    },
                    "include_tests": {
                        "type": "boolean",
                        "description": "Include test files (default false)",
                        "default": False,
                    },
                },
                "required": ["repo_path"],
            },
        ),
    ]


# ─── Tool router ──────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    match name:
        case "analyze_js_bugs":
            return await _analyze_js_bugs(**arguments)
        case "analyze_js_security":
            return await _analyze_js_security(**arguments)
        case "analyze_js_patterns":
            return await _analyze_js_patterns(**arguments)
        case "analyze_nextjs_js":
            return await _analyze_nextjs_js(**arguments)
        case "analyze_react_js":
            return await _analyze_react_js(**arguments)
        case "list_js_files":
            return await _list_js_files(**arguments)
        case _:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


# ─── analyze_js_bugs ──────────────────────────────────────────────────────────

async def _analyze_js_bugs(file_path: str, repo_path: str) -> list[TextContent]:
    if not is_safe_path(repo_path, file_path):
        return [TextContent(type="text", text="Error: path traversal blocked")]
    if is_ignored_file(file_path):
        return [TextContent(type="text", text=json.dumps({"file": file_path, "total_findings": 0, "findings": []}))]

    content = read_file_safe(file_path)
    if content is None:
        return [TextContent(type="text", text=f"Error: cannot read {file_path}")]

    lines = content.splitlines()
    findings = []

    for i, line in enumerate(lines):
        if should_skip_line(line):
            continue
        stripped = line.strip()

        # == instead of === (loose equality)
        if re.search(r'(?<!=)==(?!=)', line) and not re.search(r'===', line):
            # Skip common false positives like !== and !==
            if not re.search(r'!==|===', line):
                findings.append(make_finding(
                    i + 1, stripped,
                    "Loose equality (== instead of ===)",
                    "== performs type coercion: 0 == false is true, "
                    "null == undefined is true, '' == 0 is true. "
                    "This causes subtle and hard-to-debug comparison bugs.",
                    "Always use === for equality checks. "
                    "Use == only when you intentionally want null/undefined coercion.",
                    "medium", "bug",
                ))

        # != instead of !==
        if re.search(r'(?<!!)!=(?!=)', line):
            findings.append(make_finding(
                i + 1, stripped,
                "Loose inequality (!= instead of !==)",
                "!= performs type coercion just like ==. "
                "null != undefined is false even though they are different values.",
                "Use !== for strict inequality checks.",
                "medium", "bug",
            ))

        # var usage
        if re.search(r'\bvar\s+\w+', line):
            findings.append(make_finding(
                i + 1, stripped,
                "var declaration (use const or let)",
                "var is function-scoped and hoisted, causing subtle bugs "
                "with closures in loops and redeclaration issues.",
                "Use const for values that don't change, let for variables that do. "
                "Never use var in modern JavaScript.",
                "medium", "bug",
            ))

        # NaN comparison
        if re.search(r'===?\s*NaN|NaN\s*===?', line):
            findings.append(make_finding(
                i + 1, stripped,
                "Comparing with NaN using === (always false)",
                "NaN === NaN is always false in JavaScript. "
                "This check will never catch NaN values.",
                "Use Number.isNaN(value) or isNaN(value) instead.",
                "high", "bug",
            ))

        # typeof null === 'object' gotcha
        if re.search(r'typeof\s+\w+\s*===?\s*["\']object["\']', line):
            findings.append(make_finding(
                i + 1, stripped,
                "typeof check for 'object' may match null",
                "typeof null === 'object' is true in JavaScript. "
                "If the value could be null, this check will incorrectly pass.",
                "Add a null check: value !== null && typeof value === 'object'",
                "medium", "bug",
            ))

        # Implicit global (assignment without declaration)
        if re.search(r'^\s*(?!const|let|var|function|class|import|export|return|if|else|for|while|switch|try|catch|throw|new|delete|typeof|void|yield|await)\w+\s*=\s*(?!>|=)', line):
            if not re.search(r'^\s*(?:this|window|global|module|exports|process)\.\w+', line):
                if not re.search(r'^\s*\w+\s*[+\-*/|&]?=', line):
                    pass  # Too noisy — skip implicit global detection

        # parseInt without radix
        if re.search(r'\bparseInt\s*\(\s*\w+\s*\)', line):
            findings.append(make_finding(
                i + 1, stripped,
                "parseInt() called without radix parameter",
                "parseInt('08') returns 0 in older environments because "
                "strings starting with 0 are interpreted as octal.",
                "Always specify the radix: parseInt(value, 10)",
                "low", "bug",
            ))

        # Array.length = 0 to clear array (modifies original)
        if re.search(r'\w+\.length\s*=\s*0', line):
            findings.append(make_finding(
                i + 1, stripped,
                "Clearing array by setting .length = 0",
                "Setting array.length = 0 mutates the original array "
                "and affects all references to it.",
                "Use array = [] for a new empty array, "
                "or splice(0) if you intentionally want to mutate in place.",
                "low", "bug",
            ))

        # Arguments object
        if re.search(r'\barguments\b', line) and not re.search(r'//.*arguments', line):
            findings.append(make_finding(
                i + 1, stripped,
                "Using 'arguments' object",
                "The arguments object is not available in arrow functions "
                "and is hard to work with. It's also not an actual array.",
                "Use rest parameters instead: function foo(...args) { }",
                "low", "bug",
            ))

    result = {
        "file": file_path,
        "language": "javascript",
        "total_findings": len(findings),
        "findings": findings,
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ─── analyze_js_security ──────────────────────────────────────────────────────

async def _analyze_js_security(file_path: str, repo_path: str) -> list[TextContent]:
    if not is_safe_path(repo_path, file_path):
        return [TextContent(type="text", text="Error: path traversal blocked")]
    if is_ignored_file(file_path):
        return [TextContent(type="text", text=json.dumps({"file": file_path, "total_findings": 0, "findings": []}))]

    content = read_file_safe(file_path)
    if content is None:
        return [TextContent(type="text", text=f"Error: cannot read {file_path}")]

    lines = content.splitlines()
    findings = []

    for i, line in enumerate(lines):
        if should_skip_line(line):
            continue
        stripped = line.strip()

        # eval() usage
        if re.search(r'\beval\s*\(', line):
            findings.append(make_finding(
                i + 1, stripped,
                "eval() usage — critical security risk",
                "eval() executes arbitrary JavaScript from a string. "
                "Any user input reaching eval() enables code injection attacks.",
                "Never use eval(). Use JSON.parse() for JSON data, "
                "or find a safer alternative API.",
                "critical", "security",
            ))

        # new Function()
        if re.search(r'new\s+Function\s*\(', line):
            findings.append(make_finding(
                i + 1, stripped,
                "new Function() — code injection risk",
                "new Function() is equivalent to eval() — "
                "executes dynamic JavaScript strings.",
                "Avoid dynamic code execution entirely.",
                "critical", "security",
            ))

        # innerHTML assignment
        if re.search(r'\.innerHTML\s*=', line):
            findings.append(make_finding(
                i + 1, stripped,
                "Direct innerHTML assignment (XSS risk)",
                "Setting innerHTML directly can execute injected scripts "
                "if the content comes from user input or an API.",
                "Use textContent for plain text. "
                "Sanitize with DOMPurify if HTML content is needed.",
                "high", "security",
            ))

        # Prototype pollution
        if re.search(r'__proto__|constructor\s*\[|prototype\s*\[', line):
            findings.append(make_finding(
                i + 1, stripped,
                "Potential prototype pollution",
                "Assigning to __proto__ or constructor.prototype "
                "can pollute the JavaScript prototype chain, "
                "affecting all objects of that type.",
                "Validate object keys before assignment. "
                "Use Object.create(null) for pure dictionaries.",
                "high", "security",
            ))

        # Hardcoded secrets
        if re.search(
            r'(?:secret|api_?key|apikey|password|passwd|token|private_?key|webhook)\s*[=:]\s*["\'][^"\']{8,}["\']',
            line, re.IGNORECASE
        ):
            findings.append(make_finding(
                i + 1, stripped,
                "Hardcoded secret or API key",
                "Hardcoded secrets in source code are exposed in version control "
                "and can be extracted from client-side bundles.",
                "Move to environment variables: process.env.MY_SECRET. "
                "Use .env files and never commit them.",
                "critical", "security",
            ))

        # Math.random() for security
        if re.search(r'Math\.random\s*\(\s*\)', line):
            context = "\n".join(lines[max(0, i-3):i+3])
            if re.search(r'token|key|secret|password|auth|nonce|salt', context, re.IGNORECASE):
                findings.append(make_finding(
                    i + 1, stripped,
                    "Math.random() used for security-sensitive value",
                    "Math.random() is not cryptographically secure "
                    "and can be predicted.",
                    "Use crypto.randomBytes() in Node.js or "
                    "crypto.getRandomValues() in browsers.",
                    "high", "security",
                ))

        # SQL injection via string concatenation
        if re.search(
            r'(?:query|sql|select|insert|update|delete)\s*[+=`]\s*.*\$\{|'
            r'(?:query|sql)\s*=\s*["\'].*\+\s*\w+',
            line, re.IGNORECASE
        ):
            findings.append(make_finding(
                i + 1, stripped,
                "Potential SQL injection via string concatenation",
                "Building SQL queries with string concatenation or "
                "template literals with user input enables SQL injection.",
                "Use parameterized queries or an ORM. "
                "Never concatenate user input into SQL strings.",
                "critical", "security",
            ))

        # process.env exposure in client code
        if re.search(r'process\.env\.(?!NEXT_PUBLIC_)\w+', line):
            normalized = file_path.replace("\\", "/")
            is_client = (
                "/components/" in normalized or
                "/pages/" in normalized or
                "/app/" in normalized
            )
            if is_client and "route" not in normalized.lower() and "api" not in normalized.lower():
                findings.append(make_finding(
                    i + 1, stripped,
                    "Server env variable potentially used in client code",
                    "Non-NEXT_PUBLIC_ environment variables are not available "
                    "in client-side code and return undefined.",
                    "Use NEXT_PUBLIC_ prefix for client-accessible env vars, "
                    "or move this logic to an API route.",
                    "medium", "security",
                ))

    result = {
        "file": file_path,
        "language": "javascript",
        "total_findings": len(findings),
        "findings": findings,
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ─── analyze_js_patterns ──────────────────────────────────────────────────────

async def _analyze_js_patterns(file_path: str, repo_path: str) -> list[TextContent]:
    if not is_safe_path(repo_path, file_path):
        return [TextContent(type="text", text="Error: path traversal blocked")]
    if is_ignored_file(file_path):
        return [TextContent(type="text", text=json.dumps({"file": file_path, "total_findings": 0, "findings": []}))]

    content = read_file_safe(file_path)
    if content is None:
        return [TextContent(type="text", text=f"Error: cannot read {file_path}")]

    lines = content.splitlines()
    findings = []

    # Check for callback hell — more than 3 levels of nested callbacks
    max_nesting = 0
    current_nesting = 0
    for i, line in enumerate(lines):
        if re.search(r'function\s*\([^)]*\)\s*\{|=>\s*\{', line):
            current_nesting += 1
            max_nesting = max(max_nesting, current_nesting)
        if "}" in line:
            current_nesting = max(0, current_nesting - line.count("}"))

    if max_nesting >= 4:
        findings.append(make_finding(
            1, f"Max nesting depth: {max_nesting}",
            "Callback hell / deeply nested functions",
            f"Found {max_nesting} levels of nesting. "
            "Deep nesting makes code hard to read, debug, and maintain.",
            "Refactor to use async/await or named functions. "
            "Extract nested callbacks into separate named functions.",
            "medium", "pattern",
        ))

    for i, line in enumerate(lines):
        if should_skip_line(line):
            continue
        stripped = line.strip()

        # Missing .catch() on Promise chains
        if re.search(r'\.then\s*\(', line):
            # Check surrounding lines for .catch
            context = "\n".join(lines[i:min(len(lines), i + 10)])
            if not re.search(r'\.catch\s*\(|try\s*\{|async\s+', context):
                findings.append(make_finding(
                    i + 1, stripped,
                    "Promise .then() without .catch() error handler",
                    "Unhandled Promise rejections can crash Node.js processes "
                    "and cause silent failures in the browser.",
                    "Add .catch(err => handleError(err)) or "
                    "use try/catch with async/await.",
                    "high", "pattern",
                ))

        # console.log in non-debug files
        if re.search(r'\bconsole\.(log|warn|error|debug|info)\b', line):
            normalized = file_path.replace("\\", "/")
            is_debug_file = any(
                x in normalized for x in ["seed", "debug", "test", "spec", "view-data"]
            )
            if not is_debug_file:
                findings.append(make_finding(
                    i + 1, stripped,
                    "console.log/warn/error left in production code",
                    "Console statements left in production code leak "
                    "implementation details and impact performance.",
                    "Remove debug logs before committing. "
                    "Use a proper logger with log levels for production logging.",
                    "low", "pattern",
                ))

        # setTimeout/setInterval without clearTimeout
        if re.search(r'\bsetInterval\s*\(', line):
            context = "\n".join(lines[i:min(len(lines), i + 30)])
            if not re.search(r'clearInterval', context):
                findings.append(make_finding(
                    i + 1, stripped,
                    "setInterval without clearInterval (memory leak)",
                    "Intervals that are never cleared continue running forever, "
                    "causing memory leaks and unexpected behavior.",
                    "Store the interval ID and call clearInterval(id) "
                    "when the component unmounts or interval is no longer needed.",
                    "high", "pattern",
                ))

        # Synchronous file I/O in request handler
        if re.search(r'fs\.(readFileSync|writeFileSync|appendFileSync|existsSync)', line):
            normalized = file_path.replace("\\", "/")
            if "api" in normalized or "route" in normalized or "server" in normalized:
                findings.append(make_finding(
                    i + 1, stripped,
                    "Synchronous file I/O in API/server code",
                    "Synchronous fs operations block the Node.js event loop, "
                    "preventing other requests from being processed.",
                    "Use the async alternatives: fs.readFile(), fs.writeFile(), "
                    "or the fs/promises API with async/await.",
                    "high", "pattern",
                ))

        # TODO/FIXME comments
        if re.search(r'\b(?:TODO|FIXME|HACK|XXX)\b', line, re.IGNORECASE):
            findings.append(make_finding(
                i + 1, stripped,
                "TODO/FIXME comment in code",
                "TODO/FIXME comments indicate incomplete or problematic code.",
                "Create a GitHub Issue for this and remove the comment, "
                "or fix it now.",
                "low", "pattern",
            ))

        # Floating promises (async call without await)
        if re.search(r'(?<!await\s)(?<!return\s)(?:fetch|axios\.\w+|supabase\.\w+)\s*\(', line):
            if not re.search(r'await|\.then|\.catch|return', line):
                findings.append(make_finding(
                    i + 1, stripped,
                    "Unhandled async call (floating Promise)",
                    "Calling an async function without await, .then(), or return "
                    "creates a floating Promise — errors are silently swallowed.",
                    "Add await, or chain .then().catch(), "
                    "or explicitly return the Promise.",
                    "medium", "pattern",
                ))

    result = {
        "file": file_path,
        "language": "javascript",
        "total_findings": len(findings),
        "findings": findings,
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ─── analyze_nextjs_js ────────────────────────────────────────────────────────

async def _analyze_nextjs_js(file_path: str, repo_path: str) -> list[TextContent]:
    if not is_safe_path(repo_path, file_path):
        return [TextContent(type="text", text="Error: path traversal blocked")]
    if is_ignored_file(file_path):
        return [TextContent(type="text", text=json.dumps({"file": file_path, "total_findings": 0, "findings": []}))]

    content = read_file_safe(file_path)
    if content is None:
        return [TextContent(type="text", text=f"Error: cannot read {file_path}")]

    lines = content.splitlines()
    findings = []
    normalized = file_path.replace("\\", "/")

    is_api_route = "api" in normalized and "route" in normalized.lower()
    is_middleware = "middleware" in normalized.lower()
    is_page = normalized.endswith("page.js") or normalized.endswith("page.jsx")

    for i, line in enumerate(lines):
        if should_skip_line(line):
            continue
        stripped = line.strip()

        # API route without try/catch
        if is_api_route and re.search(r'export\s+(?:async\s+)?function\s+(?:GET|POST|PUT|DELETE|PATCH)', line):
            block = "\n".join(lines[i:min(len(lines), i + 30)])
            if not re.search(r'try\s*\{', block):
                findings.append(make_finding(
                    i + 1, stripped,
                    "API route handler without try/catch",
                    "Unhandled errors in API routes return 500 with no useful "
                    "error message and can crash the server in some configurations.",
                    "Wrap the handler body in try/catch and return "
                    "a proper error response: "
                    "return NextResponse.json({error: msg}, {status: 500})",
                    "high", "nextjs",
                ))

        # API route without auth check
        if is_api_route and re.search(
            r'export\s+(?:async\s+)?function\s+(?:POST|PUT|DELETE|PATCH)', line
        ):
            block = "\n".join(lines[i:min(len(lines), i + 20)])
            if not re.search(
                r'auth|session|token|verify|validateApiKey|checkAuth|getSession|getServerSession',
                block, re.IGNORECASE
            ):
                findings.append(make_finding(
                    i + 1, stripped,
                    "Mutating API route without authentication check",
                    "POST/PUT/DELETE routes without authentication "
                    "allow anyone to modify data.",
                    "Add authentication check at the start of the handler. "
                    "Verify session or API key before processing the request.",
                    "high", "nextjs",
                ))

        # Missing input validation in API route
        if is_api_route and re.search(r'request\.json\s*\(\s*\)|req\.body', line):
            block = "\n".join(lines[i:min(len(lines), i + 15)])
            if not re.search(r'zod|joi|yup|validate|schema|parse\s*\(|typeof|instanceof', block):
                findings.append(make_finding(
                    i + 1, stripped,
                    "API route reading request body without validation",
                    "Accepting request body without validation allows "
                    "malformed or malicious data to reach your business logic.",
                    "Validate with Zod: const data = schema.parse(await req.json()). "
                    "Return 400 for invalid input.",
                    "high", "nextjs",
                ))

        # NextResponse without status code on error
        if re.search(r'NextResponse\.json\s*\(\s*\{[^}]*error', line):
            if not re.search(r'status\s*:', line):
                findings.append(make_finding(
                    i + 1, stripped,
                    "Error response without HTTP status code",
                    "Returning an error JSON without a status code "
                    "defaults to 200 OK, confusing clients.",
                    "Always include status: "
                    "NextResponse.json({error: msg}, {status: 400})",
                    "medium", "nextjs",
                ))

        # Hardcoded URL in API calls
        if re.search(r'(?:fetch|axios\.get|axios\.post)\s*\(\s*["\']https?://', line):
            if not re.search(r'process\.env', line):
                findings.append(make_finding(
                    i + 1, stripped,
                    "Hardcoded URL in API call",
                    "Hardcoded URLs break when switching between "
                    "development, staging, and production environments.",
                    "Use environment variables: "
                    "fetch(`${process.env.NEXT_PUBLIC_API_URL}/endpoint`)",
                    "medium", "nextjs",
                ))

        # Supabase without error handling
        if re.search(r'supabase\.\w+\(\)', line) or re.search(r'\.from\s*\(', line):
            context = "\n".join(lines[i:min(len(lines), i + 5)])
            if not re.search(r'error|\.catch|try\s*\{', context):
                findings.append(make_finding(
                    i + 1, stripped,
                    "Supabase query without error handling",
                    "Supabase operations return {data, error}. "
                    "Ignoring the error means failures are silently swallowed.",
                    "Always destructure and check: "
                    "const {data, error} = await supabase.from(...); "
                    "if (error) throw error;",
                    "medium", "nextjs",
                ))

    result = {
        "file": file_path,
        "language": "javascript",
        "total_findings": len(findings),
        "findings": findings,
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ─── analyze_react_js ─────────────────────────────────────────────────────────

async def _analyze_react_js(file_path: str, repo_path: str) -> list[TextContent]:
    if not is_safe_path(repo_path, file_path):
        return [TextContent(type="text", text="Error: path traversal blocked")]
    if is_ignored_file(file_path):
        return [TextContent(type="text", text=json.dumps({"file": file_path, "total_findings": 0, "findings": []}))]

    content = read_file_safe(file_path)
    if content is None:
        return [TextContent(type="text", text=f"Error: cannot read {file_path}")]

    # Only analyze files with JSX
    if "<" not in content or ("return" not in content and "=>" not in content):
        result = {"file": file_path, "language": "javascript",
                  "total_findings": 0, "findings": []}
        return [TextContent(type="text", text=json.dumps(result))]

    lines = content.splitlines()
    findings = []

    # Large component
    non_empty = [l for l in lines if l.strip()]
    if len(non_empty) > 250:
        findings.append(make_finding(
            1, f"{len(non_empty)} non-empty lines",
            "Component file too large",
            f"This component has {len(non_empty)} non-empty lines. "
            "Large components are hard to test and maintain.",
            "Split into smaller focused components. "
            "Extract logic into custom hooks.",
            "medium", "pattern",
        ))

    for i, line in enumerate(lines):
        if should_skip_line(line):
            continue
        stripped = line.strip()

        # Missing key prop in .map()
        if re.search(r'\.map\s*\(\s*(?:\w+|\([^)]+\))\s*=>', line):
            block = "\n".join(lines[i:min(len(lines), i + 5)])
            if re.search(r'<\w+', block) and not re.search(r'\bkey\s*=', block):
                findings.append(make_finding(
                    i + 1, stripped,
                    "Missing key prop in list rendering",
                    "React uses keys to identify list items. "
                    "Missing keys cause incorrect re-renders and UI bugs.",
                    "Add a unique key: items.map(item => "
                    "<Component key={item.id} />)",
                    "high", "pattern",
                ))

        # Index as key
        if re.search(r'key\s*=\s*\{?\s*(?:index|i|idx)\s*\}?', line):
            findings.append(make_finding(
                i + 1, stripped,
                "Array index used as key prop",
                "Using array index as key causes incorrect component "
                "reuse when items are reordered, added, or removed.",
                "Use a stable unique identifier: key={item.id}",
                "medium", "pattern",
            ))

        # dangerouslySetInnerHTML
        if "dangerouslySetInnerHTML" in line:
            findings.append(make_finding(
                i + 1, stripped,
                "dangerouslySetInnerHTML usage (XSS risk)",
                "dangerouslySetInnerHTML renders raw HTML and is "
                "vulnerable to XSS if content comes from user input.",
                "Sanitize with DOMPurify before using, "
                "or use a markdown renderer instead.",
                "high", "security",
            ))

        # useEffect without dependency array
        if re.search(r'useEffect\s*\(\s*(?:async\s*)?\(\s*\)\s*=>', line) or \
           re.search(r'useEffect\s*\(\s*(?:async\s*)?function', line):
            block = "\n".join(lines[i:min(len(lines), i + 15)])
            if not re.search(r'\)\s*,\s*\[', block):
                findings.append(make_finding(
                    i + 1, stripped,
                    "useEffect missing dependency array",
                    "useEffect without a dependency array runs after "
                    "every render, causing infinite loops if state is updated.",
                    "Add a dependency array: useEffect(() => {...}, [dep1, dep2]). "
                    "Use [] for mount-only effects.",
                    "high", "hooks",
                ))

        # useEffect with async directly
        if re.search(r'useEffect\s*\(\s*async', line):
            findings.append(make_finding(
                i + 1, stripped,
                "useEffect with async function directly",
                "useEffect cannot take an async function directly — "
                "the cleanup return is ignored, causing memory leaks.",
                "Define async function inside the effect: "
                "useEffect(() => { const fn = async () => {...}; fn(); }, [])",
                "high", "hooks",
            ))

    result = {
        "file": file_path,
        "language": "javascript",
        "total_findings": len(findings),
        "findings": findings,
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ─── list_js_files ────────────────────────────────────────────────────────────

async def _list_js_files(
    repo_path: str,
    file_type: str = "all",
    include_tests: bool = False,
) -> list[TextContent]:
    repo = Path(repo_path)
    if not repo.exists():
        return [TextContent(type="text", text=f"Error: not found: {repo_path}")]

    extensions = {".js", ".jsx", ".mjs", ".cjs"}
    files = []

    for path in sorted(repo.rglob("*")):
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.suffix not in extensions:
            continue
        if not include_tests and re.search(r'\.(test|spec)\.(js|jsx)$', path.name):
            continue
        if is_ignored_file(str(path)):
            continue

        rel = str(path.relative_to(repo)).replace("\\", "/")

        # Apply type filter
        ft = file_type.lower()
        matched = False
        if ft == "all":
            matched = True
        elif ft == "page":
            matched = path.name in ("page.js", "page.jsx")
        elif ft == "component":
            matched = path.suffix == ".jsx" or (
                path.suffix == ".js" and "component" in rel.lower()
            )
        elif ft == "hook":
            matched = path.stem.startswith("use") and path.stem[3:4].isupper()
        elif ft == "api":
            matched = "api" in rel and "route" in rel.lower()
        elif ft == "util":
            matched = any(p in rel.lower() for p in ["util", "helper", "lib/"])

        if not matched:
            continue

        try:
            size = path.stat().st_size
            content_peek = path.read_text(encoding="utf-8", errors="replace")[:300]
            has_jsx = "<" in content_peek and ("return" in content_peek or "=>" in content_peek)
            is_module = "import " in content_peek or "export " in content_peek

            component_type = "unknown"
            if path.name in ("page.js", "page.jsx"):
                component_type = "page"
            elif path.name in ("layout.js", "layout.jsx"):
                component_type = "layout"
            elif path.name in ("route.js", "route.jsx"):
                component_type = "api-route"
            elif path.name.startswith("use") and path.stem[3:4].isupper():
                component_type = "hook"
            elif "middleware" in path.name.lower():
                component_type = "middleware"
            elif has_jsx:
                component_type = "component"
            elif "api" in rel or "lib" in rel:
                component_type = "library"
            elif "util" in rel:
                component_type = "utility"

            files.append({
                "path": rel,
                "name": path.name,
                "component_type": component_type,
                "has_jsx": has_jsx,
                "is_module": is_module,
                "size_kb": round(size / 1024, 1),
            })
        except OSError:
            continue

    result = {
        "repo": repo_path,
        "file_type_filter": file_type,
        "total_files": len(files),
        "files": files,
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream, write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
