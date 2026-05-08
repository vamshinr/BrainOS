"use client";

import { useState } from "react";
import { ModelPicker } from "@/components/model-picker";

const SUGGESTIONS = [
  "Who owns the billing service?",
  "How do we deploy backend to production?",
  "What gotchas should I know about Stripe webhooks?",
  "What policies apply to PRs in billing-svc?",
  "What does P0 mean here?",
  "When is the Adyen sunset?",
];

type Feedback = { confidence: number; grounded: boolean; feedback: string };
type Answer = {
  question: string;
  answer: string;
  used: string[];
  retrieved_texts: string[];
  latency_ms: number | null;
  feedback: Feedback | null;
};

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<Answer[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [model, setModel] = useState("");

  async function ask(q: string) {
    setErr(null);
    setLoading(true);
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, model: model || undefined }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setHistory((h) => [
        {
          question: q,
          answer: j.answer,
          used: j.used ?? [],
          retrieved_texts: j.retrieved_texts ?? [],
          latency_ms: j.latency_ms ?? null,
          feedback: j.feedback ?? null,
        },
        ...h,
      ]);
      setQuestion("");
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="px-10 py-10 max-w-3xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Ask
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Query the brain.</h1>
      <p className="mt-2 text-[var(--muted-foreground)]">
        Answers are grounded in ChromaDB-retrieved knowledge units from the AMD MI300X 70B model.
      </p>

      <form
        onSubmit={(e) => { e.preventDefault(); if (question.trim()) ask(question.trim()); }}
        className="mt-6 space-y-3"
      >
        <div className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask anything about how the company works…"
            className="flex-1 rounded-md border bg-[var(--card)] px-3 py-2.5 text-sm"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            {loading ? "Retrieving…" : "Ask"}
          </button>
        </div>
        <div className="max-w-md">
          <ModelPicker
            value={model}
            onChange={setModel}
            mode="text"
            label="Answer model (optional override)"
            hint="affects execute + feedback"
          />
        </div>
      </form>

      <div className="mt-3 flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => ask(s)}
            disabled={loading}
            className="text-xs rounded-full border bg-[var(--card)] px-3 py-1 hover:border-[var(--accent)]/40 disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>

      {err && (
        <div className="mt-4 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {err}
        </div>
      )}

      <div className="mt-8 space-y-6">
        {history.map((h, i) => (
          <div key={i} className="rounded-lg border bg-[var(--card)] px-5 py-4">
            <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">
              Question
            </div>
            <div className="text-sm font-medium">{h.question}</div>

            <div className="mt-4 text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">
              Answer
            </div>
            <div className="text-sm leading-relaxed whitespace-pre-wrap">{h.answer}</div>

            {/* Metadata row */}
            <div className="mt-4 flex flex-wrap items-center gap-3 text-[11px] text-[var(--muted-foreground)]">
              {h.latency_ms !== null && (
                <span className="rounded bg-[var(--muted)]/40 px-2 py-0.5 font-mono">
                  {h.latency_ms} ms · AMD MI300X
                </span>
              )}
              {h.retrieved_texts.length > 0 && (
                <span>
                  {h.retrieved_texts.length} unit{h.retrieved_texts.length !== 1 ? "s" : ""} retrieved
                </span>
              )}
              {h.feedback && (
                <span
                  className={`rounded px-2 py-0.5 ${
                    h.feedback.grounded
                      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
                      : "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
                  }`}
                >
                  {h.feedback.grounded ? "Grounded" : "Ungrounded"} ·{" "}
                  conf {h.feedback.confidence.toFixed(2)}
                </span>
              )}
            </div>

            {h.feedback?.feedback && (
              <div className="mt-2 text-[11px] text-[var(--muted-foreground)] italic">
                {h.feedback.feedback}
              </div>
            )}

            {/* Retrieved context — shows exactly what the model was given */}
            {h.retrieved_texts.length > 0 && (
              <details className="mt-3">
                <summary className="text-[11px] text-[var(--muted-foreground)] cursor-pointer hover:text-[var(--foreground)] select-none">
                  Retrieved context ({h.retrieved_texts.length} units sent to model)
                </summary>
                <ol className="mt-2 space-y-1 pl-1">
                  {h.retrieved_texts.map((t, idx) => (
                    <li key={idx} className="text-[11px] text-[var(--muted-foreground)] flex gap-2">
                      <span className="font-mono shrink-0 text-[var(--accent)]">{idx + 1}.</span>
                      <span>{t}</span>
                    </li>
                  ))}
                </ol>
              </details>
            )}

            {h.retrieved_texts.length === 0 && h.used.length === 0 && (
              <div className="mt-2 text-[11px] text-amber-600 dark:text-amber-400">
                No units retrieved — brain may be empty or query didn&apos;t match any stored knowledge.
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
