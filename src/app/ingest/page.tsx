"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

const KINDS = [
  { value: "slack", label: "Slack" },
  { value: "email", label: "Email" },
  { value: "ticket", label: "Support ticket" },
  { value: "doc", label: "Doc / runbook" },
  { value: "meeting", label: "Meeting notes" },
  { value: "wiki", label: "Wiki" },
  { value: "code", label: "Code / PR" },
  { value: "other", label: "Other" },
] as const;

type Result = {
  sourceId: string;
  addedUnits: number;
  addedEntities: number;
  totals: { sources: number; entities: number; units: number };
};

export default function IngestPage() {
  const router = useRouter();
  const [kind, setKind] = useState<(typeof KINDS)[number]["value"]>("slack");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setResult(null);
    setLoading(true);
    try {
      const res = await fetch("/api/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind,
          title,
          content,
          url: url || undefined,
        }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setResult(j);
      setTitle("");
      setContent("");
      setUrl("");
      router.refresh();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="px-10 py-10 max-w-3xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Ingest
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">
        Drop in a knowledge source.
      </h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-xl">
        Paste a Slack thread, email, support ticket, or doc. The brain extracts
        atomic facts, processes, decisions, owners, policies, and gotchas — and
        reconciles them against what it already knows.
      </p>

      <form onSubmit={submit} className="mt-8 space-y-4">
        <div className="grid grid-cols-[160px_1fr] gap-3">
          <Field label="Source type">
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as typeof kind)}
              className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
            >
              {KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Title">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              placeholder="e.g. #eng-billing — Stripe migration kickoff"
              className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
            />
          </Field>
        </div>

        <Field label="Source URL (optional)">
          <input
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://…"
            className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
          />
        </Field>

        <Field label="Content">
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            required
            rows={14}
            placeholder="Paste the raw thread / email / ticket / doc here. Don't summarize — the brain works better on raw content."
            className="w-full rounded-md border bg-[var(--card)] px-3 py-3 text-sm font-mono leading-relaxed"
          />
        </Field>

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={loading || !title || !content}
            className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            {loading ? "Extracting…" : "Extract knowledge"}
          </button>
          {loading && (
            <span className="text-xs text-[var(--muted-foreground)]">
              Calling LLM, parsing entities & units, reconciling…
            </span>
          )}
        </div>
      </form>

      {err && (
        <div className="mt-6 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {err}
        </div>
      )}

      {result && (
        <div className="mt-6 rounded-md border border-emerald-300 bg-emerald-50 dark:bg-emerald-950/30 dark:border-emerald-800 px-4 py-3 text-sm">
          <div className="font-medium">
            Extracted {result.addedUnits} knowledge units and{" "}
            {result.addedEntities} entities.
          </div>
          <div className="text-xs text-[var(--muted-foreground)] mt-1">
            Brain now contains {result.totals.units} units across{" "}
            {result.totals.entities} entities from {result.totals.sources}{" "}
            sources.{" "}
            <a className="underline" href="/">
              View dashboard →
            </a>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
        {label}
      </div>
      {children}
    </label>
  );
}
