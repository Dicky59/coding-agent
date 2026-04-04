import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Coding Agent Dashboard",
  description: "Browse and analyze AI code review reports",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-[#0f1117] text-slate-200 antialiased">
        <header className="border-b border-slate-700 bg-[#0f1117] sticky top-0 z-50">
          <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
            <a href="/" className="flex items-center gap-3 hover:opacity-80 transition-opacity">
              <span className="text-2xl">🤖</span>
              <div>
                <div className="font-bold text-white text-lg leading-tight">
                  AI Coding Agent
                </div>
                <div className="text-xs text-slate-400">Code Review Dashboard</div>
              </div>
            </a>

            <nav className="flex items-center gap-6">
              <a href="/" className="text-sm text-slate-400 hover:text-white transition-colors">
                Reports
              </a>
              <a href="/trends" className="text-sm text-slate-400 hover:text-white transition-colors">
                📈 Trends
              </a>
              <a href="/settings" className="text-sm text-slate-400 hover:text-white transition-colors">
                ⚙️ Settings
              </a>
              <a
                href="https://github.com/Dicky59/coding-agent"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm text-slate-400 hover:text-white transition-colors flex items-center gap-1"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
                </svg>
                GitHub
              </a>
            </nav>
          </div>
        </header>

        <main className="max-w-7xl mx-auto px-6 py-8">
          {children}
        </main>

        <footer className="border-t border-slate-800 mt-16 py-6 text-center text-slate-600 text-sm">
          AI Coding Agent Dashboard · Built with Next.js + Supabase
        </footer>
      </body>
    </html>
  );
}
