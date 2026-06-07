"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { GraphDump, MnemEvent } from "@/lib/mnemosyne";

function fmtTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function Home() {
  const [data, setData] = useState<GraphDump | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/graph")
      .then((r) => r.json())
      .then((d: GraphDump) => setData({ events: d.events ?? [], edges: d.edges ?? [] }))
      .catch(() => setData({ events: [], edges: [] }))
      .finally(() => setLoading(false));
  }, []);

  const events = data?.events ?? [];
  const edges = data?.edges ?? [];
  const recent: MnemEvent[] = [...events]
    .sort((a, b) => new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime())
    .slice(0, 8);

  return (
    <div className="px-4 sm:px-6 md:px-10 py-6 md:py-10 max-w-3xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Mnemosyne
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Causal memory engine.</h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-xl">
        Stores timestamped events and the directed cause → effect edges between them, then answers
        “why did X happen?” by walking the causal graph — not by returning a bag of similar chunks.
      </p>

      <div className="mt-6 grid grid-cols-2 sm:grid-cols-2 gap-3 max-w-sm">
        <Stat label="Events" value={loading ? "…" : events.length} />
        <Stat label="Causal edges" value={loading ? "…" : edges.length} />
      </div>

      <div className="mt-6 flex flex-wrap gap-2">
        <Cta href="/ingest" label="Ingest" hint="add events" />
        <Cta href="/ask" label="Ask" hint="why did X happen?" />
        <Cta href="/graph" label="Map" hint="causal graph" />
      </div>

      <div className="mt-10">
        <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
          Recent events
        </div>
        {loading ? (
          <div className="text-sm text-[var(--muted-foreground)]">Loading…</div>
        ) : recent.length === 0 ? (
          <div className="rounded-md border border-dashed border-[var(--border)] bg-[var(--muted)]/20 px-6 py-10 text-center text-sm text-[var(--muted-foreground)]">
            Nothing ingested yet. <Link className="underline" href="/ingest">Add your first events</Link>.
          </div>
        ) : (
          <ul className="space-y-1.5">
            {recent.map((e) => (
              <li key={e.id} className="flex items-baseline gap-3 rounded-md border bg-[var(--card)] px-3 py-2">
                <span className="text-xs font-mono text-[var(--muted-foreground)] tabular-nums shrink-0">
                  {fmtTime(e.occurred_at)}
                </span>
                <span className="text-sm">{e.summary}</span>
                {(e.reinforcement_count ?? 0) > 0 && (
                  <span className="ml-auto text-[10px] font-mono text-[var(--muted-foreground)] shrink-0">
                    ×{(e.reinforcement_count ?? 0) + 1}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-md border bg-[var(--card)] px-4 py-3">
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">{label}</div>
    </div>
  );
}

function Cta({ href, label, hint }: { href: string; label: string; hint: string }) {
  return (
    <Link
      href={href}
      className="rounded-md border bg-[var(--card)] px-4 py-2 hover:border-[var(--foreground)] transition-colors"
    >
      <div className="text-sm font-medium">{label}</div>
      <div className="text-[11px] text-[var(--muted-foreground)]">{hint}</div>
    </Link>
  );
}
