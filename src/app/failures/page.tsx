"use client";

import { useState } from "react";
import Link from "next/link";

type Episode = {
  rule: "tool_call_repeat" | "apply_revert" | "same_error_retry";
  tool?: string;
  filePath?: string;
  errorSignature?: string;
  occurrences: number;
  summary: string;
  evidenceQuote: string;
};

type DetectResponse = {
  eventCount: number;
  episodes: Episode[];
};

type IngestResponse = {
  job_id?: string;
  title?: string;
  queue_position?: number;
  episodes?: Episode[];
  narrative?: { title: string; content: string };
  error?: string;
};

const RULE_LABEL: Record<Episode["rule"], string> = {
  tool_call_repeat: "Repeated failing tool-call",
  apply_revert: "Apply-then-revert loop",
  same_error_retry: "Same-error retry loop",
};

const RULE_TINT: Record<Episode["rule"], string> = {
  tool_call_repeat: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  apply_revert: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  same_error_retry: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
};

const EXAMPLE_TRACE = `[
  {"tool":"Bash","args":{"command":"npm run build"},"error":"TS2307: Cannot find module './types' from /repo/src/index.ts"},
  {"tool":"Bash","args":{"command":"npm run build"},"error":"TS2307: Cannot find module './types' from /repo/src/index.ts"},
  {"tool":"Bash","args":{"command":"npm run build --verbose"},"error":"TS2307: Cannot find module './types' from /repo/src/index.ts"},
  {"tool":"Edit","args":{"file_path":"src/index.ts","old_string":"import { X } from './types'","new_string":"import { X } from './typings'"}},
  {"tool":"Bash","args":{"command":"npm run build"},"error":"TS2307: Cannot find module './typings' from /repo/src/index.ts"},
  {"tool":"Edit","args":{"file_path":"src/index.ts","old_string":"import { X } from './typings'","new_string":"import { X } from './types'"}},
  {"tool":"Bash","args":{"command":"npm run build"},"error":"TS2307: Cannot find module './types' from /repo/src/index.ts"}
]`;

export default function FailuresPage() {
  const [transcript, setTranscript] = useState("");
  const [repoLabel, setRepoLabel] = useState("");
  const [detected, setDetected] = useState<DetectResponse | null>(null);
  const [ingested, setIngested] = useState<IngestResponse | null>(null);
  const [loading, setLoading] = useState<"detect" | "ingest" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function detect() {
    setErr(null);
    setIngested(null);
    setLoading("detect");
    try {
      const res = await fetch("/api/failures/detect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setDetected(j);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(null);
    }
  }

  async function ingest() {
    setErr(null);
    setLoading("ingest");
    try {
      const res = await fetch("/api/failures/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transcript,
          repoLabel: repoLabel || undefined,
        }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setIngested(j);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="px-10 py-10 max-w-4xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Agent failure memory
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">
        Turn a thrashing transcript into a durable gotcha.
      </h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-2xl">
        Paste a Claude Code or Cursor trace where the agent looped, retried, or
        ping-ponged a fix. BrainOS detects the thrash pattern, extracts a{" "}
        <strong className="text-[var(--foreground)]">gotcha</strong> unit, and
        adds a{" "}
        <code className="text-xs">Known Agent Traps</code> section to your
        SKILLS.md — so the <em>next</em> agent skips the loop.
      </p>

      <div className="mt-6 grid grid-cols-[1fr_220px] gap-3">
        <label className="block">
          <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
            Transcript (JSON array of tool calls, or pasted log)
          </div>
          <textarea
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            rows={14}
            placeholder={EXAMPLE_TRACE}
            className="w-full rounded-md border bg-[var(--card)] px-3 py-3 text-xs font-mono leading-relaxed"
          />
        </label>
        <div className="space-y-3">
          <label className="block">
            <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
              Repo label (optional)
            </div>
            <input
              value={repoLabel}
              onChange={(e) => setRepoLabel(e.target.value)}
              placeholder="brainos-main"
              className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
            />
          </label>
          <button
            type="button"
            onClick={() => setTranscript(EXAMPLE_TRACE)}
            className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-xs hover:border-[var(--accent)]/40"
          >
            Load example trace
          </button>
        </div>
      </div>

      <div className="mt-4 flex gap-2">
        <button
          onClick={detect}
          disabled={!transcript || loading !== null}
          className="rounded-md border bg-[var(--card)] px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          {loading === "detect" ? "Detecting…" : "Detect thrash"}
        </button>
        <button
          onClick={ingest}
          disabled={!transcript || loading !== null}
          className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          {loading === "ingest" ? "Extracting…" : "Extract → BrainOS"}
        </button>
      </div>

      {err && (
        <div className="mt-4 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {err}
        </div>
      )}

      {detected && (
        <section className="mt-8">
          <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
            Detected episodes · {detected.eventCount} events parsed
          </div>
          {detected.episodes.length === 0 ? (
            <div className="rounded-md border bg-[var(--card)] px-4 py-3 text-sm text-[var(--muted-foreground)]">
              No thrash pattern detected. Try a trace with ≥3 failing tool calls
              that share a tool name, file path, or error.
            </div>
          ) : (
            <ul className="space-y-2">
              {detected.episodes.map((ep, i) => (
                <li
                  key={i}
                  className="rounded-lg border bg-[var(--card)] px-4 py-3"
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={`mt-0.5 inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${RULE_TINT[ep.rule]}`}
                    >
                      {RULE_LABEL[ep.rule]} · {ep.occurrences}×
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm leading-snug">{ep.summary}</div>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
                        {ep.tool && <span>tool: <code>{ep.tool}</code></span>}
                        {ep.filePath && <span>· file: <code>{ep.filePath}</code></span>}
                        {ep.errorSignature && (
                          <span>· error: <code className="truncate">{ep.errorSignature.slice(0, 80)}</code></span>
                        )}
                      </div>
                      <div className="mt-2 text-[11px] font-mono text-[var(--muted-foreground)] line-clamp-2">
                        &quot;{ep.evidenceQuote}&quot;
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {ingested && (
        <section className="mt-8 rounded-md border border-emerald-300 bg-emerald-50 dark:bg-emerald-950/30 dark:border-emerald-800 px-4 py-3 text-sm">
          <div className="font-medium">
            Queued: <span className="font-normal">{ingested.title ?? ingested.narrative?.title}</span>
          </div>
          <div className="text-xs text-[var(--muted-foreground)] mt-1.5">
            {ingested.queue_position && ingested.queue_position > 1
              ? `Position #${ingested.queue_position}. The dock in the bottom-right will update when the extractor runs.`
              : "Starting now — watch the dock in the bottom-right for live progress."}
          </div>
          <div className="mt-3 flex gap-3 text-xs">
            <Link href="/" className="underline underline-offset-2">
              View brain →
            </Link>
            <Link href="/skills" className="underline underline-offset-2">
              Export SKILLS.md (Known Agent Traps) →
            </Link>
          </div>
          {ingested.narrative && (
            <details className="mt-3 text-xs">
              <summary className="cursor-pointer text-[var(--muted-foreground)]">
                Show synthesized narrative
              </summary>
              <pre className="mt-2 rounded-md bg-[var(--muted)]/30 p-3 font-mono whitespace-pre-wrap break-words">
                {ingested.narrative.content}
              </pre>
            </details>
          )}
        </section>
      )}
    </div>
  );
}
