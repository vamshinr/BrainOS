"use client";

import { useEffect, useState } from "react";
import type {
  RetrieveResult,
  CausalResult,
  AssociativeResult,
  MnemEvent,
} from "@/lib/mnemosyne";
import { relationColor } from "@/lib/mnemosyne";

type Mode = "causal" | "associative";

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<Mode>("causal");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<RetrieveResult | null>(null);

  // Resolve distractor ids -> summaries for display.
  const [eventsById, setEventsById] = useState<Record<string, MnemEvent>>({});
  useEffect(() => {
    fetch("/api/graph")
      .then((r) => r.json())
      .then((g: { events?: MnemEvent[] }) => {
        const map: Record<string, MnemEvent> = {};
        (g.events ?? []).forEach((e) => (map[e.id] = e));
        setEventsById(map);
      })
      .catch(() => {});
  }, [result]);

  async function ask(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setErr(null);
    setResult(null);
    setLoading(true);
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, mode, k: 8 }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setResult(j as RetrieveResult);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="px-4 sm:px-6 md:px-10 py-6 md:py-10 max-w-3xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Ask
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Ask why something happened.</h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-xl">
        <strong>Causal</strong> mode anchors on the event you ask about, walks the cause → effect
        graph to the root cause and consequences, and explains the chain.{" "}
        <strong>Associative</strong> mode is the plain semantic-search baseline — kept only to show
        the difference.
      </p>

      <form onSubmit={ask} className="mt-6 space-y-3">
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          placeholder="Why did checkout start throwing 500s?"
          className="w-full rounded-md border bg-[var(--card)] px-3 py-3 text-sm"
        />
        <div className="flex items-center gap-3">
          <div className="flex gap-1 rounded-lg border bg-[var(--muted)]/30 p-1">
            {(["causal", "associative"] as Mode[]).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium capitalize transition-colors ${
                  mode === m
                    ? "bg-[var(--foreground)] text-[var(--background)]"
                    : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            {loading ? "Thinking…" : "Ask"}
          </button>
        </div>
      </form>

      {err && (
        <div className="mt-6 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {err}
        </div>
      )}

      {result?.mode === "causal" && <CausalView result={result} eventsById={eventsById} />}
      {result?.mode === "associative" && <AssociativeView result={result} />}
    </div>
  );
}

function CausalView({
  result,
  eventsById,
}: {
  result: CausalResult;
  eventsById: Record<string, MnemEvent>;
}) {
  if (!result.chain.length) {
    return (
      <div className="mt-6 text-sm text-[var(--muted-foreground)]">
        No matching events. Ingest some text first.
      </div>
    );
  }
  return (
    <div className="mt-8 space-y-6">
      {result.answer && (
        <div className="rounded-md border bg-[var(--card)] px-4 py-4">
          <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
            Why
          </div>
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{result.answer}</p>
        </div>
      )}

      <div>
        <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
          Causal chain · root → outcome
        </div>
        <ol className="relative border-l border-[var(--border)] ml-2">
          {result.chain.map((entry) => {
            const isAnchor = entry.event.id === result.anchor_event_id;
            return (
              <li key={entry.event.id} className="ml-4 pb-5">
                <div
                  className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full"
                  style={{ background: relationColor(entry.incoming_relation) }}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-mono text-[var(--muted-foreground)] tabular-nums">
                    {fmtTime(entry.event.occurred_at)}
                  </span>
                  {entry.incoming_relation ? (
                    <span
                      className="rounded px-1.5 py-0.5 text-[10px] font-mono text-white"
                      style={{ background: relationColor(entry.incoming_relation) }}
                    >
                      {entry.incoming_relation} {entry.confidence?.toFixed(2)}
                    </span>
                  ) : (
                    <span className="rounded bg-[var(--muted)] px-1.5 py-0.5 text-[10px] font-mono text-[var(--muted-foreground)]">
                      root cause
                    </span>
                  )}
                  {isAnchor && (
                    <span className="rounded border border-[var(--border)] px-1.5 py-0.5 text-[10px] font-mono text-[var(--muted-foreground)]">
                      ← your query
                    </span>
                  )}
                </div>
                <div className="mt-1 text-sm">{entry.event.summary}</div>
                {entry.event.tags?.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {entry.event.tags.map((t) => (
                      <span key={t} className="text-[10px] text-[var(--muted-foreground)] font-mono">
                        #{t}
                      </span>
                    ))}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </div>

      {result.excluded_distractors.length > 0 && (
        <div className="rounded-md border border-dashed border-[var(--border)] bg-[var(--muted)]/20 px-4 py-3">
          <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
            Excluded distractors
          </div>
          <p className="text-xs text-[var(--muted-foreground)] mb-2">
            Keyword-similar events that are <strong>not</strong> on any causal path — associative
            search would wrongly surface these:
          </p>
          <ul className="space-y-1">
            {result.excluded_distractors.map((id) => (
              <li key={id} className="text-xs">
                <span className="line-through decoration-[var(--muted-foreground)]/50">
                  {eventsById[id]?.summary ?? id}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function AssociativeView({ result }: { result: AssociativeResult }) {
  return (
    <div className="mt-8">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Associative baseline · top-{result.chunks.length} by similarity
      </div>
      <p className="text-xs text-[var(--muted-foreground)] mb-3">
        A bag of semantically-similar events, unordered and with no causal structure. Note how
        keyword-similar distractors creep in.
      </p>
      <ul className="space-y-2">
        {result.chunks.map((c) => (
          <li key={c.id} className="flex items-start gap-3 rounded-md border bg-[var(--card)] px-3 py-2">
            <span className="text-xs font-mono text-[var(--muted-foreground)] tabular-nums mt-0.5">
              {c.score.toFixed(3)}
            </span>
            <span className="text-sm">
              {c.event?.summary ?? (c.payload?.summary as string) ?? c.id}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
