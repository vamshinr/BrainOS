"use client";

import { useCallback, useEffect, useState } from "react";
import type { GraphDump } from "@/lib/mnemosyne";
import { CausalGraph } from "@/components/causal-graph";
import { RELATION_COLORS } from "@/lib/mnemosyne";

export default function GraphPage() {
  const [data, setData] = useState<GraphDump | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    fetch("/api/graph")
      .then((r) => r.json())
      .then((d: GraphDump) => setData({ events: d.events ?? [], edges: d.edges ?? [] }))
      .catch(() => setData({ events: [], edges: [] }))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
    const onIngested = () => load();
    window.addEventListener("mnemosyne:ingested", onIngested);
    return () => window.removeEventListener("mnemosyne:ingested", onIngested);
  }, [load]);

  const events = data?.events ?? [];
  const edges = data?.edges ?? [];

  return (
    <div className="px-4 sm:px-6 md:px-10 py-6 md:py-10">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Map
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Causal graph</h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-xl">
        Every ingested event placed on a time axis, linked by the inferred cause → effect edges.
        Hover an event to isolate what it caused and what caused it.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-[var(--muted-foreground)]">
        <span className="font-mono tabular-nums">
          {events.length} events · {edges.length} edges
        </span>
        <span className="flex flex-wrap gap-3">
          {Object.entries(RELATION_COLORS).map(([rel, color]) => (
            <span key={rel} className="flex items-center gap-1">
              <span className="inline-block h-2 w-3 rounded-sm" style={{ background: color }} />
              {rel}
            </span>
          ))}
        </span>
      </div>

      <div className="mt-5">
        {loading ? (
          <div className="text-sm text-[var(--muted-foreground)]">Loading…</div>
        ) : events.length === 0 ? (
          <div className="rounded-md border border-dashed border-[var(--border)] bg-[var(--muted)]/20 px-6 py-12 text-center text-sm text-[var(--muted-foreground)]">
            No events yet. <a className="underline" href="/ingest">Ingest some text</a> to build the
            causal graph.
          </div>
        ) : (
          <CausalGraph data={{ events, edges }} />
        )}
      </div>
    </div>
  );
}
