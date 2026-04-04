"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { supabase } from "@/lib/supabase";
import { formatDate } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Settings {
  id: number;
  weekly_scan_enabled: boolean;
  scan_day: string;
  scan_repos: string[];
  last_scan_at: string | null;
  next_scan_at: string | null;
  updated_at: string;
}

const AVAILABLE_REPOS = [
  { name: "DailyPulse", language: "kotlin", icon: "🤖" },
  { name: "next-store", language: "typescript", icon: "📘" },
  { name: "next-dicky", language: "javascript", icon: "💛" },
  { name: "spring-petclinic", language: "java", icon: "☕" },
];

const DAYS = [
  { value: "monday",    label: "Monday"    },
  { value: "tuesday",   label: "Tuesday"   },
  { value: "wednesday", label: "Wednesday" },
  { value: "thursday",  label: "Thursday"  },
  { value: "friday",    label: "Friday"    },
];

// ─── Components ───────────────────────────────────────────────────────────────

function Toggle({
  enabled,
  onChange,
}: {
  enabled: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={() => onChange(!enabled)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
        enabled ? "bg-indigo-600" : "bg-slate-600"
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
          enabled ? "translate-x-6" : "translate-x-1"
        }`}
      />
    </button>
  );
}

function StatusBadge({ enabled }: { enabled: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${
        enabled
          ? "bg-green-950 text-green-300 border border-green-800"
          : "bg-slate-700 text-slate-400 border border-slate-600"
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${enabled ? "bg-green-400 animate-pulse" : "bg-slate-500"}`} />
      {enabled ? "Active" : "Paused"}
    </span>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [saved, setSaved] = useState(false);
  const [triggerStatus, setTriggerStatus] = useState<"idle" | "success" | "error">("idle");

  useEffect(() => {
    async function fetchSettings() {
      const { data } = await supabase
        .from("settings")
        .select("*")
        .eq("id", 1)
        .single();
      if (data) setSettings(data);
      setLoading(false);
    }
    fetchSettings();
  }, []);

  async function saveSettings(updates: Partial<Settings>) {
    if (!settings) return;
    setSaving(true);
    setSaved(false);

    const updated = { ...settings, ...updates, updated_at: new Date().toISOString() };
    setSettings(updated);

    const { error } = await supabase
      .from("settings")
      .update(updates)
      .eq("id", 1);

    setSaving(false);
    if (!error) {
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    }
  }

  async function triggerManualScan() {
    setTriggering(true);
    setTriggerStatus("idle");

    try {
      // Trigger GitHub Actions workflow via API
      const resp = await fetch(
        "https://api.github.com/repos/Dicky59/coding-agent/actions/workflows/scheduled-scan.yml/dispatches",
        {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${process.env.NEXT_PUBLIC_GITHUB_TOKEN || ""}`,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            ref: "main",
            inputs: {
              force: "true",
              repos: settings?.scan_repos.join(",") || "",
            },
          }),
        }
      );

      if (resp.status === 204) {
        setTriggerStatus("success");
      } else {
        setTriggerStatus("error");
      }
    } catch {
      setTriggerStatus("error");
    }

    setTriggering(false);
  }

  function toggleRepo(repoName: string) {
    if (!settings) return;
    const current = settings.scan_repos || [];
    const updated = current.includes(repoName)
      ? current.filter((r) => r !== repoName)
      : [...current, repoName];
    saveSettings({ scan_repos: updated });
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-400">
        <div className="text-center">
          <div className="text-3xl mb-3 animate-pulse">⚙️</div>
          <p>Loading settings...</p>
        </div>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="text-center py-24">
        <div className="text-5xl mb-4">❌</div>
        <p className="text-slate-400">Could not load settings from Supabase.</p>
      </div>
    );
  }

  return (
    <div className="max-w-2xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold text-white">Settings</h1>
          <p className="text-slate-400 mt-1">Configure automated scans</p>
        </div>
        <Link href="/" className="text-indigo-400 hover:text-indigo-300 text-sm transition-colors">
          ← Dashboard
        </Link>
      </div>

      {/* Weekly scan toggle */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-6 mb-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-slate-200 font-semibold">Weekly Automatic Scan</h2>
            <p className="text-slate-400 text-sm mt-1">
              Automatically scan all configured repos on a schedule
            </p>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge enabled={settings.weekly_scan_enabled} />
            <Toggle
              enabled={settings.weekly_scan_enabled}
              onChange={(v) => saveSettings({ weekly_scan_enabled: v })}
            />
          </div>
        </div>

        {/* Scan day selector */}
        <div className="mt-4 pt-4 border-t border-slate-700">
          <label className="text-slate-300 text-sm font-medium">Scan day</label>
          <div className="flex gap-2 mt-2 flex-wrap">
            {DAYS.map((day) => (
              <button
                key={day.value}
                onClick={() => saveSettings({ scan_day: day.value })}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  settings.scan_day === day.value
                    ? "bg-indigo-600 text-white"
                    : "bg-slate-700 text-slate-400 hover:bg-slate-600"
                }`}
              >
                {day.label}
              </button>
            ))}
          </div>
          <p className="text-slate-500 text-xs mt-2">
            Scans run at 8:00 AM UTC on the selected day
          </p>
        </div>

        {/* Last / next scan */}
        <div className="mt-4 pt-4 border-t border-slate-700 grid grid-cols-2 gap-4">
          <div>
            <p className="text-slate-500 text-xs">Last scan</p>
            <p className="text-slate-300 text-sm mt-0.5">
              {settings.last_scan_at ? formatDate(settings.last_scan_at) : "Never"}
            </p>
          </div>
          <div>
            <p className="text-slate-500 text-xs">Next scan</p>
            <p className="text-slate-300 text-sm mt-0.5">
              {settings.weekly_scan_enabled
                ? settings.next_scan_at
                  ? formatDate(settings.next_scan_at)
                  : "Next Monday 8:00 AM UTC"
                : "Paused"}
            </p>
          </div>
        </div>
      </div>

      {/* Repos to scan */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-6 mb-4">
        <h2 className="text-slate-200 font-semibold mb-1">Repos to Scan</h2>
        <p className="text-slate-400 text-sm mb-4">
          Choose which projects are included in automatic scans
        </p>
        <div className="space-y-2">
          {AVAILABLE_REPOS.map((repo) => {
            const enabled = settings.scan_repos?.includes(repo.name) ?? false;
            return (
              <div
                key={repo.name}
                className="flex items-center justify-between py-3 px-4 bg-slate-900/50 rounded-lg"
              >
                <div className="flex items-center gap-3">
                  <span className="text-xl">{repo.icon}</span>
                  <div>
                    <p className="text-slate-200 text-sm font-medium">{repo.name}</p>
                    <p className="text-slate-500 text-xs capitalize">{repo.language}</p>
                  </div>
                </div>
                <Toggle enabled={enabled} onChange={() => toggleRepo(repo.name)} />
              </div>
            );
          })}
        </div>
      </div>

      {/* Manual trigger */}
      <div className="bg-slate-800/50 border border-slate-700 rounded-xl p-6 mb-4">
        <h2 className="text-slate-200 font-semibold mb-1">Manual Scan</h2>
        <p className="text-slate-400 text-sm mb-4">
          Trigger a scan right now for all configured repos.
          This runs the GitHub Actions workflow immediately.
        </p>
        <button
          onClick={triggerManualScan}
          disabled={triggering}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-600 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
        >
          {triggering ? (
            <>
              <span className="animate-spin">⏳</span>
              Triggering...
            </>
          ) : (
            <>🔄 Run Scan Now</>
          )}
        </button>

        {triggerStatus === "success" && (
          <div className="mt-3 flex items-center gap-2 text-green-400 text-sm">
            <span>✅</span>
            <span>Scan triggered! Check the</span>
            <a
              href="https://github.com/Dicky59/coding-agent/actions"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-green-300"
            >
              GitHub Actions tab
            </a>
            <span>for progress.</span>
          </div>
        )}
        {triggerStatus === "error" && (
          <div className="mt-3 text-red-400 text-sm">
            ❌ Could not trigger scan. Check that NEXT_PUBLIC_GITHUB_TOKEN is set in Vercel env vars.
          </div>
        )}
      </div>

      {/* Save indicator */}
      {(saving || saved) && (
        <div className={`fixed bottom-6 right-6 px-4 py-2 rounded-lg text-sm font-medium shadow-lg transition-all ${
          saved ? "bg-green-700 text-green-100" : "bg-slate-700 text-slate-200"
        }`}>
          {saving ? "💾 Saving..." : "✅ Saved!"}
        </div>
      )}
    </div>
  );
}
