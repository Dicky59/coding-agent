import { useState, useRef, useEffect } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Message {
  id: string;
  role: "user" | "agent";
  content: string;
  timestamp: Date;
  isLoading?: boolean;
}

interface RepoSummary {
  total_files: number;
  total_lines: number;
  detected_frameworks: string[];
  language_breakdown: Record<string, { files: number; size_kb: number }>;
}

// ─── API ──────────────────────────────────────────────────────────────────────

const API_BASE = "http://localhost:8000";

async function analyzeRepo(repoPath: string, question: string): Promise<string> {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_path: repoPath, question }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Analysis failed");
  }
  const data = await res.json();
  return data.result;
}

async function getQuickSummary(repoPath: string): Promise<string> {
  const res = await fetch(`${API_BASE}/quick-summary`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_path: repoPath }),
  });
  if (!res.ok) throw new Error("Summary failed");
  const data = await res.json();
  return data.summary;
}

// ─── Suggestion chips ─────────────────────────────────────────────────────────

const SUGGESTIONS = [
  "What are the main REST endpoints?",
  "Summarize the architecture",
  "List all React components",
  "Find Spring Boot services",
  "What dependencies are used?",
  "Show me the data models",
  "Where is business logic?",
  "Find all TODO comments",
];

// ─── Language colors ──────────────────────────────────────────────────────────

const LANG_COLORS: Record<string, string> = {
  kotlin: "#A97BFF",
  java: "#F89820",
  typescript: "#3178C6",
  javascript: "#F7DF1E",
  python: "#3572A5",
  css: "#563D7C",
  xml: "#E44D26",
  gradle: "#02303A",
  yaml: "#CB171E",
  json: "#8BC34A",
  markdown: "#083FA1",
};

// ─── Markdown renderer (simple) ───────────────────────────────────────────────

function renderMarkdown(text: string): string {
  return text
    .replace(/^### (.+)$/gm, '<h3 class="md-h3">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="md-h2">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 class="md-h1">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code class="md-code">$1</code>')
    .replace(/```(\w+)?\n([\s\S]+?)```/g, '<pre class="md-pre"><code>$2</code></pre>')
    .replace(/^- (.+)$/gm, '<li class="md-li">$1</li>')
    .replace(/(<li.*<\/li>\n?)+/g, '<ul class="md-ul">$&</ul>')
    .replace(/\n\n/g, '</p><p class="md-p">')
    .replace(/^(?!<[huplo])/gm, '')
    .trim();
}

// ─── Components ───────────────────────────────────────────────────────────────

function TypingDots() {
  return (
    <div style={{ display: "flex", gap: 4, alignItems: "center", padding: "4px 0" }}>
      {[0, 1, 2].map(i => (
        <div key={i} style={{
          width: 7, height: 7,
          borderRadius: "50%",
          background: "var(--accent)",
          animation: `bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
        }} />
      ))}
    </div>
  );
}

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user";
  return (
    <div style={{
      display: "flex",
      justifyContent: isUser ? "flex-end" : "flex-start",
      marginBottom: 16,
      animation: "fadeSlideIn 0.3s ease",
    }}>
      {!isUser && (
        <div style={{
          width: 32, height: 32,
          borderRadius: 8,
          background: "linear-gradient(135deg, var(--accent), var(--accent2))",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 14, marginRight: 10, flexShrink: 0, alignSelf: "flex-start",
          marginTop: 4,
        }}>⚡</div>
      )}
      <div style={{
        maxWidth: "78%",
        background: isUser
          ? "linear-gradient(135deg, var(--accent), var(--accent2))"
          : "var(--surface2)",
        borderRadius: isUser ? "16px 16px 4px 16px" : "16px 16px 16px 4px",
        padding: "12px 16px",
        color: isUser ? "#fff" : "var(--text)",
        fontSize: 14,
        lineHeight: 1.6,
        border: !isUser ? "1px solid var(--border)" : "none",
        boxShadow: isUser ? "0 4px 12px rgba(99,102,241,0.3)" : "none",
      }}>
        {msg.isLoading ? (
          <TypingDots />
        ) : isUser ? (
          <span>{msg.content}</span>
        ) : (
          <div
            className="agent-response"
            dangerouslySetInnerHTML={{ __html: `<p class="md-p">${renderMarkdown(msg.content)}</p>` }}
          />
        )}
      </div>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [repoPath, setRepoPath] = useState("/path/to/your/repo");
  const [repoConnected, setRepoConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [repoSummaryRaw, setRepoSummaryRaw] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const connectRepo = async () => {
    setConnecting(true);
    try {
      const summary = await getQuickSummary(repoPath);
      setRepoSummaryRaw(summary);
      setRepoConnected(true);
      setMessages([{
        id: Date.now().toString(),
        role: "agent",
        content: `Repository connected! Here's what I found:\n\n${summary}`,
        timestamp: new Date(),
      }]);
    } catch (e: any) {
      alert(`Failed to connect: ${e.message}`);
    } finally {
      setConnecting(false);
    }
  };

  const sendMessage = async (text?: string) => {
    const question = (text || input).trim();
    if (!question || !repoConnected || isThinking) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content: question,
      timestamp: new Date(),
    };
    const loadingMsg: Message = {
      id: (Date.now() + 1).toString(),
      role: "agent",
      content: "",
      timestamp: new Date(),
      isLoading: true,
    };

    setMessages(prev => [...prev, userMsg, loadingMsg]);
    setInput("");
    setIsThinking(true);

    try {
      const result = await analyzeRepo(repoPath, question);
      setMessages(prev =>
        prev.map(m => m.id === loadingMsg.id
          ? { ...m, content: result, isLoading: false }
          : m
        )
      );
    } catch (e: any) {
      setMessages(prev =>
        prev.map(m => m.id === loadingMsg.id
          ? { ...m, content: `Error: ${e.message}`, isLoading: false }
          : m
        )
      );
    } finally {
      setIsThinking(false);
    }
  };

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Syne:wght@400;500;600;700;800&display=swap');

        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        :root {
          --bg: #0a0a0f;
          --surface: #111118;
          --surface2: #1a1a24;
          --surface3: #22222e;
          --border: #2a2a3a;
          --text: #e8e8f0;
          --text2: #8888a0;
          --accent: #6366f1;
          --accent2: #8b5cf6;
          --accent3: #06b6d4;
          --success: #10b981;
          --warning: #f59e0b;
          --font-ui: 'Syne', sans-serif;
          --font-mono: 'JetBrains Mono', monospace;
        }

        body {
          background: var(--bg);
          color: var(--text);
          font-family: var(--font-ui);
          height: 100vh;
          overflow: hidden;
        }

        @keyframes bounce {
          0%, 60%, 100% { transform: translateY(0); }
          30% { transform: translateY(-6px); }
        }
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        @keyframes shimmer {
          0% { background-position: -200% center; }
          100% { background-position: 200% center; }
        }

        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

        .agent-response h1, .agent-response h2, .agent-response h3 { 
          color: var(--text); font-family: var(--font-ui); margin: 12px 0 6px;
        }
        .agent-response .md-h2 { font-size: 15px; font-weight: 700; color: var(--accent3); }
        .agent-response .md-h3 { font-size: 14px; font-weight: 600; color: var(--text2); }
        .agent-response .md-code {
          background: var(--surface3); color: var(--accent3);
          padding: 1px 6px; border-radius: 4px; font-family: var(--font-mono); font-size: 12px;
        }
        .agent-response .md-pre {
          background: var(--surface3); border: 1px solid var(--border);
          border-radius: 8px; padding: 12px; margin: 8px 0;
          overflow-x: auto; font-family: var(--font-mono); font-size: 12px;
        }
        .agent-response .md-ul { padding-left: 16px; margin: 6px 0; }
        .agent-response .md-li { margin: 3px 0; color: var(--text); }
        .agent-response .md-p { margin: 4px 0; }
        .agent-response strong { color: var(--text); font-weight: 600; }
      `}</style>

      <div style={{ display: "flex", height: "100vh", background: "var(--bg)" }}>

        {/* ── Sidebar ── */}
        <div style={{
          width: 280,
          background: "var(--surface)",
          borderRight: "1px solid var(--border)",
          display: "flex",
          flexDirection: "column",
          padding: "20px 16px",
          gap: 20,
          flexShrink: 0,
        }}>
          {/* Logo */}
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 36, height: 36,
              background: "linear-gradient(135deg, var(--accent), var(--accent2))",
              borderRadius: 10,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 18,
            }}>⚡</div>
            <div>
              <div style={{ fontWeight: 800, fontSize: 15, letterSpacing: "-0.3px" }}>
                CodeAgent
              </div>
              <div style={{ fontSize: 11, color: "var(--text2)" }}>Phase 1 · Repo Reader</div>
            </div>
          </div>

          {/* Repo input */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <label style={{ fontSize: 11, fontWeight: 600, color: "var(--text2)", letterSpacing: "0.5px", textTransform: "uppercase" }}>
              Repository Path
            </label>
            <input
              value={repoPath}
              onChange={e => setRepoPath(e.target.value)}
              disabled={repoConnected}
              style={{
                background: "var(--surface2)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: "8px 10px",
                color: "var(--text)",
                fontSize: 11,
                fontFamily: "var(--font-mono)",
                outline: "none",
                opacity: repoConnected ? 0.5 : 1,
              }}
              placeholder="/path/to/repo"
            />
            <button
              onClick={repoConnected ? () => { setRepoConnected(false); setMessages([]); setRepoSummaryRaw(null); } : connectRepo}
              disabled={connecting}
              style={{
                background: repoConnected
                  ? "transparent"
                  : "linear-gradient(135deg, var(--accent), var(--accent2))",
                border: repoConnected ? "1px solid var(--border)" : "none",
                borderRadius: 8,
                padding: "9px 0",
                color: repoConnected ? "var(--text2)" : "#fff",
                fontSize: 13,
                fontWeight: 600,
                cursor: connecting ? "wait" : "pointer",
                fontFamily: "var(--font-ui)",
                transition: "all 0.2s",
              }}
            >
              {connecting ? "Connecting..." : repoConnected ? "Disconnect" : "Connect Repo"}
            </button>
          </div>

          {/* Status */}
          <div style={{
            background: "var(--surface2)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: "10px 12px",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}>
            <div style={{
              width: 8, height: 8,
              borderRadius: "50%",
              background: repoConnected ? "var(--success)" : "var(--text2)",
              boxShadow: repoConnected ? "0 0 8px var(--success)" : "none",
              animation: repoConnected ? "pulse 2s infinite" : "none",
            }} />
            <span style={{ fontSize: 12, color: repoConnected ? "var(--success)" : "var(--text2)" }}>
              {repoConnected ? "Repo connected" : "No repo connected"}
            </span>
          </div>

          {/* Suggestions */}
          {repoConnected && (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text2)", letterSpacing: "0.5px", textTransform: "uppercase" }}>
                Quick Questions
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {SUGGESTIONS.map(s => (
                  <button
                    key={s}
                    onClick={() => sendMessage(s)}
                    disabled={isThinking}
                    style={{
                      background: "var(--surface2)",
                      border: "1px solid var(--border)",
                      borderRadius: 6,
                      padding: "7px 10px",
                      color: "var(--text2)",
                      fontSize: 12,
                      textAlign: "left",
                      cursor: "pointer",
                      fontFamily: "var(--font-ui)",
                      transition: "all 0.15s",
                    }}
                    onMouseEnter={e => {
                      (e.target as HTMLElement).style.color = "var(--text)";
                      (e.target as HTMLElement).style.borderColor = "var(--accent)";
                    }}
                    onMouseLeave={e => {
                      (e.target as HTMLElement).style.color = "var(--text2)";
                      (e.target as HTMLElement).style.borderColor = "var(--border)";
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Main chat area ── */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>

          {/* Header */}
          <div style={{
            padding: "16px 24px",
            borderBottom: "1px solid var(--border)",
            background: "var(--surface)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 16 }}>Repository Analysis</div>
              <div style={{ fontSize: 12, color: "var(--text2)", fontFamily: "var(--font-mono)" }}>
                {repoConnected ? repoPath : "Connect a repository to begin"}
              </div>
            </div>
            {isThinking && (
              <div style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "6px 12px",
                background: "var(--surface2)",
                border: "1px solid var(--accent)",
                borderRadius: 20,
              }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--accent)", animation: "pulse 1s infinite" }} />
                <span style={{ fontSize: 12, color: "var(--accent)" }}>Agent thinking...</span>
              </div>
            )}
          </div>

          {/* Messages */}
          <div style={{
            flex: 1,
            overflowY: "auto",
            padding: "24px",
            display: "flex",
            flexDirection: "column",
          }}>
            {messages.length === 0 && (
              <div style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: 16,
                color: "var(--text2)",
              }}>
                <div style={{ fontSize: 48 }}>⚡</div>
                <div style={{ fontSize: 20, fontWeight: 700, color: "var(--text)" }}>
                  AI Coding Agent
                </div>
                <div style={{ fontSize: 14, textAlign: "center", maxWidth: 400, lineHeight: 1.6 }}>
                  Connect a repository to start analyzing your Kotlin, Java, Spring Boot, React, or Android codebase.
                </div>
              </div>
            )}
            {messages.map(msg => (
              <MessageBubble key={msg.id} msg={msg} />
            ))}
            <div ref={chatEndRef} />
          </div>

          {/* Input */}
          <div style={{
            padding: "16px 24px",
            borderTop: "1px solid var(--border)",
            background: "var(--surface)",
          }}>
            <div style={{
              display: "flex",
              gap: 10,
              background: "var(--surface2)",
              border: "1px solid var(--border)",
              borderRadius: 12,
              padding: "4px 4px 4px 16px",
              transition: "border-color 0.2s",
            }}
              onFocus={() => {}}
            >
              <input
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === "Enter" && !e.shiftKey && sendMessage()}
                disabled={!repoConnected || isThinking}
                placeholder={repoConnected ? "Ask anything about this codebase..." : "Connect a repo first"}
                style={{
                  flex: 1,
                  background: "none",
                  border: "none",
                  outline: "none",
                  color: "var(--text)",
                  fontSize: 14,
                  fontFamily: "var(--font-ui)",
                  padding: "10px 0",
                }}
              />
              <button
                onClick={() => sendMessage()}
                disabled={!repoConnected || !input.trim() || isThinking}
                style={{
                  background: (repoConnected && input.trim() && !isThinking)
                    ? "linear-gradient(135deg, var(--accent), var(--accent2))"
                    : "var(--surface3)",
                  border: "none",
                  borderRadius: 8,
                  width: 40, height: 40,
                  cursor: (repoConnected && input.trim() && !isThinking) ? "pointer" : "not-allowed",
                  color: "#fff",
                  fontSize: 16,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  transition: "all 0.2s",
                  flexShrink: 0,
                }}
              >
                →
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
