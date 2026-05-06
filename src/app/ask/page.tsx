"use client";

import { useState } from "react";

const SUGGESTIONS = [
  "Who owns the billing service?",
  "How do we deploy backend to production?",
  "What gotchas should I know about Stripe webhooks?",
  "What policies apply to PRs in billing-svc?",
  "What does P0 mean here?",
  "When is the Adyen sunset?",
];

type Answer = { question: string; answer: string; used: string[] };

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<Answer[]>([]);
  const [err, setErr] = useState<string | null>(null);

  async function ask(q: string) {
    setErr(null);
    setLoading(true);
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setHistory((h) => [{ question: q, answer: j.answer, used: j.used }, ...h]);
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
      <h1 className="text-3xl font-semibold tracking-tight">
        Query the brain.
      </h1>
      <p className="mt-2 text-[var(--muted-foreground)]">
        Answers are grounded only in extracted knowledge units, with citation
        IDs.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (question.trim()) ask(question.trim());
        }}
        className="mt-6 flex gap-2"
      >
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
          {loading ? "Thinking…" : "Ask"}
        </button>
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
          <div
            key={i}
            className="rounded-lg border bg-[var(--card)] px-5 py-4"
          >
            <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">
              Question
            </div>
            <div className="text-sm font-medium">{h.question}</div>
            <div className="mt-4 text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">
              Answer
            </div>
            <div className="text-sm leading-relaxed whitespace-pre-wrap">
              {h.answer}
            </div>
            {h.used.length > 0 && (
              <div className="mt-3 text-[11px] text-[var(--muted-foreground)]">
                Cited units: {h.used.slice(0, 8).join(", ")}
                {h.used.length > 8 && ` +${h.used.length - 8} more`}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
