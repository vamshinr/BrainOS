"use client";

import { useState, useRef } from "react";
import type { IngestResult } from "@/lib/mnemosyne";
import { relationColor } from "@/lib/mnemosyne";

type Tab = "text" | "file";

export default function IngestPage() {
  const [tab, setTab] = useState<Tab>("text");

  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");

  const [fileTitle, setFileTitle] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResult | null>(null);

  async function submitText(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setResult(null);
    setLoading(true);
    try {
      const res = await fetch("/api/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, source_id: title || undefined }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setResult(j as IngestResult);
      setContent("");
      setTitle("");
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }

  async function submitFile(e: React.FormEvent) {
    e.preventDefault();
    if (!uploadFile) return;
    setErr(null);
    setResult(null);
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", uploadFile, uploadFile.name);
      if (fileTitle) fd.append("title", fileTitle);
      const res = await fetch("/api/ingest-file", { method: "POST", body: fd });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setResult(j as IngestResult);
      setFileTitle("");
      setUploadFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="px-4 sm:px-6 md:px-10 py-6 md:py-10 max-w-3xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Ingest
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Add events to memory.</h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-xl">
        Paste text or upload a text file. Mnemosyne extracts timestamped <strong>events</strong>,
        infers the directed <strong>cause → effect edges</strong> between them, and stores them in
        the causal graph.
      </p>

      <div className="mt-6 flex gap-1 rounded-lg border bg-[var(--muted)]/30 p-1 w-fit">
        {([
          { id: "text", label: "Text / Paste" },
          { id: "file", label: "Text file" },
        ] as { id: Tab; label: string }[]).map((t) => (
          <button
            key={t.id}
            onClick={() => { setTab(t.id); setErr(null); setResult(null); }}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              tab === t.id
                ? "bg-[var(--foreground)] text-[var(--background)]"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "text" && (
        <form onSubmit={submitText} className="mt-8 space-y-4">
          <Field label="Source label (optional)">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. incident-2026-06-06"
              className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
            />
          </Field>
          <Field label="Content">
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
              rows={14}
              placeholder="Paste a log, a chat thread, or an incident timeline. Include times so events can be ordered — e.g. 'At 14:02 the cache TTL was cut to 30s. At 14:19 checkout threw 500s, triggered by the saturated DB pool.'"
              className="w-full rounded-md border bg-[var(--card)] px-3 py-3 text-sm font-mono leading-relaxed"
            />
          </Field>
          <SubmitRow loading={loading} disabled={!content} />
        </form>
      )}

      {tab === "file" && (
        <form onSubmit={submitFile} className="mt-8 space-y-4">
          <div className="rounded-md border border-dashed border-[var(--border)] bg-[var(--muted)]/20 px-4 py-3 text-sm text-[var(--muted-foreground)]">
            Upload a <strong>.txt</strong>, <strong>.md</strong>, <strong>.csv</strong>,{" "}
            <strong>.log</strong>, or <strong>.json</strong> file. (PDF/Word are not supported —
            Mnemosyne ingests text.)
          </div>
          <Field label="Source label (optional)">
            <input
              value={fileTitle}
              onChange={(e) => setFileTitle(e.target.value)}
              placeholder="e.g. ops-runbook"
              className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
            />
          </Field>
          <Field label="File (.txt, .md, .csv, .log, .json)">
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.md,.markdown,.csv,.log,.json,text/plain,text/markdown,text/csv"
              onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
              required
              className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-[var(--foreground)] file:text-[var(--background)] file:px-3 file:py-1 file:text-xs file:font-medium"
            />
          </Field>
          {uploadFile && (
            <div className="text-[11px] text-[var(--muted-foreground)]">
              {uploadFile.name} · {(uploadFile.size / 1024).toFixed(1)} KB
            </div>
          )}
          <SubmitRow loading={loading} disabled={!uploadFile} />
        </form>
      )}

      {err && (
        <div className="mt-6 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {err}
        </div>
      )}

      {result && <IngestSummary result={result} />}
    </div>
  );
}

function IngestSummary({ result }: { result: IngestResult }) {
  const { counts, edges_created, events_reinforced } = result;
  return (
    <div className="mt-6 rounded-md border border-emerald-300 bg-emerald-50 dark:bg-emerald-950/30 dark:border-emerald-800 px-4 py-4 space-y-3">
      <div className="text-sm font-medium">
        Ingested {counts.created} event{counts.created === 1 ? "" : "s"} ·{" "}
        {counts.edges} causal edge{counts.edges === 1 ? "" : "s"}
        {counts.reinforced > 0 && ` · ${counts.reinforced} reinforced`}
      </div>

      {events_reinforced.length > 0 && (
        <div className="text-xs text-[var(--muted-foreground)]">
          Near-duplicates reinforced instead of duplicated:{" "}
          {events_reinforced.map((r) => `${r.event_id.slice(0, 8)} (×${r.reinforcement_count})`).join(", ")}
        </div>
      )}

      {edges_created.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
            Causal edges inferred
          </div>
          {edges_created
            .slice()
            .sort((a, b) => b.confidence - a.confidence)
            .map((e) => (
              <div key={e.id} className="flex items-center gap-2 text-xs font-mono">
                <span
                  className="rounded px-1.5 py-0.5 text-white"
                  style={{ background: relationColor(e.relation) }}
                >
                  {e.relation}
                </span>
                <span className="text-[var(--muted-foreground)]">
                  {e.cause_id.slice(0, 8)} → {e.effect_id.slice(0, 8)}
                </span>
                <span className="ml-auto tabular-nums">{e.confidence.toFixed(2)}</span>
              </div>
            ))}
        </div>
      )}

      <a href="/graph" className="inline-block text-xs underline text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
        View the causal map →
      </a>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
        {label}
      </div>
      {children}
    </label>
  );
}

function SubmitRow({ loading, disabled }: { loading: boolean; disabled: boolean }) {
  return (
    <div className="flex items-center gap-3 pt-2">
      <button
        type="submit"
        disabled={loading || disabled}
        className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium disabled:opacity-50"
      >
        {loading ? "Extracting…" : "Extract events"}
      </button>
      {loading && (
        <span className="text-xs text-[var(--muted-foreground)]">
          Extracting events and inferring causal edges (Haiku)…
        </span>
      )}
    </div>
  );
}
