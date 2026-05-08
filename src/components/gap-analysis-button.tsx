"use client";

import { useState } from "react";

type Gap = {
  severity: "high" | "medium" | "low";
  kind: string;
  entity: string;
  message: string;
  unitId?: string;
  conflictsWith?: string[];
};

type Result = {
  gaps: Gap[];
  counts: { high: number; medium: number; low: number; total: number };
};

const SEV_TINT: Record<Gap["severity"], string> = {
  high: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300 border-red-200 dark:border-red-800",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 border-amber-200 dark:border-amber-800",
  low: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 border-zinc-200 dark:border-zinc-700",
};

export function GapAnalysisButton() {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run() {
    setLoading(true);
    setErr(null);
    try {
      const res = await fetch("/api/analyze/gaps", { method: "POST" });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setResult(j);
      setOpen(true);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button
        onClick={run}
        disabled={loading}
        className="text-xs rounded-md border border-[var(--border)] px-3 py-2 hover:bg-[var(--muted)] disabled:opacity-50 transition-colors"
      >
        {loading ? "Analyzing…" : "🔍 Analyze knowledge gaps"}
      </button>
      {err && <p className="text-[11px] text-red-600">{err}</p>}

      {open && result && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-6" onClick={() => setOpen(false)}>
          <div
            className="w-full max-w-2xl max-h-[80vh] overflow-hidden rounded-xl border bg-[var(--background)] shadow-xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="px-5 py-4 border-b flex items-center justify-between">
              <div>
                <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">Gap analysis</div>
                <h2 className="text-lg font-semibold mt-0.5">What the brain doesn&apos;t know</h2>
              </div>
              <button onClick={() => setOpen(false)} className="text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
                ✕
              </button>
            </header>

            <div className="px-5 py-3 border-b flex items-center gap-3 text-xs">
              <span className={`rounded px-2 py-1 border ${SEV_TINT.high}`}>
                {result.counts.high} high
              </span>
              <span className={`rounded px-2 py-1 border ${SEV_TINT.medium}`}>
                {result.counts.medium} medium
              </span>
              <span className={`rounded px-2 py-1 border ${SEV_TINT.low}`}>
                {result.counts.low} low
              </span>
              <span className="ml-auto text-[var(--muted-foreground)]">
                {result.counts.total} total
              </span>
            </div>

            <ul className="flex-1 overflow-y-auto px-5 py-3 space-y-2">
              {result.gaps.length === 0 ? (
                <li className="text-sm text-[var(--muted-foreground)] py-8 text-center">
                  ✨ No gaps found. Brain looks complete.
                </li>
              ) : (
                result.gaps.map((g, i) => (
                  <li key={i} className="rounded-lg border bg-[var(--card)] px-3 py-2.5">
                    <div className="flex items-start gap-2">
                      <span className={`shrink-0 mt-0.5 text-[10px] font-semibold uppercase tracking-wider rounded px-1.5 py-0.5 border ${SEV_TINT[g.severity]}`}>
                        {g.severity}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm">{g.message}</div>
                        <div className="mt-1 text-[10px] text-[var(--muted-foreground)] font-mono">
                          {g.kind}
                          {g.entity && ` · ${g.entity}`}
                        </div>
                      </div>
                    </div>
                  </li>
                ))
              )}
            </ul>

            <footer className="px-5 py-3 border-t text-[11px] text-[var(--muted-foreground)]">
              Detected by graph traversal — no LLM call needed.
            </footer>
          </div>
        </div>
      )}
    </>
  );
}
