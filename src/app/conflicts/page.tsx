"use client";

import { useCallback, useEffect, useState } from "react";

type Unit = {
  id: string;
  subject: string;
  statement: string;
  kind: string;
  confidence: number;
  createdAt: string;
  updatedAt?: string;
  department?: string;
  temporalStatus?: string;
  evidence?: { sourceId?: string; quote?: string }[];
  disputed?: boolean;
  conflictsWith?: string[];
};

type ConflictPair = {
  unit_a: Unit;
  unit_b: Unit;
};

type ConflictsResponse = {
  conflicts: ConflictPair[];
  total: number;
  error?: string;
};

const KIND_COLOR: Record<string, string> = {
  fact: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
  process: "bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300",
  decision: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  ownership: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  definition: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  policy: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  gotcha: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
};

function UnitCard({
  unit,
  isWinner,
  onPick,
  resolving,
}: {
  unit: Unit;
  isWinner: boolean | null;
  onPick: () => void;
  resolving: boolean;
}) {
  const kindClass = KIND_COLOR[unit.kind] ?? "bg-[var(--muted)]/40 text-[var(--foreground)]";
  const quote = unit.evidence?.[0]?.quote;

  return (
    <div
      className={`flex-1 rounded-lg border p-4 transition-all ${
        isWinner === true
          ? "border-emerald-500 bg-emerald-50/60 dark:bg-emerald-950/30"
          : isWinner === false
          ? "border-[var(--border)] opacity-50"
          : "border-[var(--border)] bg-[var(--card)]"
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        <span className={`text-[10px] font-semibold uppercase tracking-widest rounded px-2 py-0.5 ${kindClass}`}>
          {unit.kind}
        </span>
        {unit.department && (
          <span className="text-[10px] text-[var(--muted-foreground)] rounded bg-[var(--muted)]/40 px-2 py-0.5">
            {unit.department}
          </span>
        )}
      </div>

      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">
        {unit.subject}
      </div>
      <p className="text-sm leading-relaxed font-medium">{unit.statement}</p>

      {quote && (
        <blockquote className="mt-3 border-l-2 border-[var(--border)] pl-3 text-[11px] text-[var(--muted-foreground)] italic line-clamp-3">
          {quote}
        </blockquote>
      )}

      <div className="mt-3 flex items-center gap-3 text-[10px] text-[var(--muted-foreground)]">
        <span>conf {unit.confidence?.toFixed(2) ?? "—"}</span>
        {unit.temporalStatus && (
          <span className="rounded bg-[var(--muted)]/40 px-1.5 py-0.5">{unit.temporalStatus}</span>
        )}
        <span className="font-mono opacity-60">{unit.id.slice(0, 8)}</span>
      </div>

      <button
        onClick={onPick}
        disabled={resolving}
        className={`mt-4 w-full rounded-md py-2 text-sm font-medium transition-colors disabled:opacity-50 ${
          isWinner === true
            ? "bg-emerald-600 text-white"
            : "bg-[var(--foreground)] text-[var(--background)] hover:opacity-90"
        }`}
      >
        {isWinner === true ? "✓ This wins" : "This one wins"}
      </button>
    </div>
  );
}

export default function ConflictsPage() {
  const [data, setData] = useState<ConflictsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [resolving, setResolving] = useState<string | null>(null);
  const [resolved, setResolved] = useState<Set<string>>(new Set());
  const [winners, setWinners] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await fetch("/api/conflicts", { cache: "no-store" });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setData(j);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function resolve(winnerId: string, loserId: string, pairKey: string) {
    setResolving(pairKey);
    setWinners((w) => ({ ...w, [pairKey]: winnerId }));
    try {
      const res = await fetch("/api/conflicts/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ winner_id: winnerId, loser_id: loserId }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setResolved((s) => new Set([...s, pairKey]));
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
      setWinners((w) => { const n = { ...w }; delete n[pairKey]; return n; });
    } finally {
      setResolving(null);
    }
  }

  const activePairs = data?.conflicts.filter(
    (p) => !resolved.has(`${p.unit_a.id}-${p.unit_b.id}`)
  ) ?? [];

  return (
    <div className="px-4 sm:px-6 md:px-10 py-6 md:py-10 max-w-5xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Conflicts
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Resolve disputed facts.</h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-2xl">
        These are knowledge units the brain cannot reconcile automatically — two sources
        make contradictory claims with no temporal signal. Pick the one that&apos;s correct;
        the other becomes historical.
      </p>

      {loading && (
        <div className="mt-10 text-sm text-[var(--muted-foreground)] animate-pulse">
          Loading conflicts…
        </div>
      )}

      {err && (
        <div className="mt-6 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {err}
        </div>
      )}

      {!loading && data && (
        <>
          <div className="mt-6 flex items-center gap-4">
            <div className="flex items-center gap-2 rounded-lg border bg-[var(--card)] px-4 py-2">
              <span className="text-2xl font-bold">{activePairs.length}</span>
              <span className="text-sm text-[var(--muted-foreground)]">open conflicts</span>
            </div>
            {resolved.size > 0 && (
              <div className="flex items-center gap-2 rounded-lg border border-emerald-300 bg-emerald-50 dark:bg-emerald-950/30 px-4 py-2">
                <span className="text-2xl font-bold text-emerald-700 dark:text-emerald-300">
                  {resolved.size}
                </span>
                <span className="text-sm text-emerald-700 dark:text-emerald-300">resolved</span>
              </div>
            )}
            <button
              onClick={load}
              className="ml-auto text-xs rounded-md border bg-[var(--card)] px-3 py-1.5 hover:bg-[var(--background)] transition-colors"
            >
              Refresh
            </button>
          </div>

          {activePairs.length === 0 && (
            <div className="mt-12 rounded-lg border border-dashed bg-[var(--muted)]/30 px-6 py-12 text-center">
              <div className="text-4xl mb-3">✓</div>
              <div className="text-sm font-medium">No open conflicts</div>
              <div className="mt-1 text-[var(--muted-foreground)] text-sm">
                {resolved.size > 0
                  ? `You resolved ${resolved.size} conflict${resolved.size !== 1 ? "s" : ""} this session.`
                  : "The brain has no disputed facts. Ingest more knowledge to surface contradictions."}
              </div>
            </div>
          )}

          <div className="mt-8 space-y-8">
            {activePairs.map((pair) => {
              const pairKey = `${pair.unit_a.id}-${pair.unit_b.id}`;
              const pickedWinner = winners[pairKey];
              const isResolvingThis = resolving === pairKey;

              return (
                <div key={pairKey} className="rounded-xl border bg-[var(--background)] p-5 shadow-sm">
                  <div className="flex items-center gap-2 mb-4">
                    <span className="text-[10px] uppercase tracking-widest font-semibold text-rose-600 dark:text-rose-400 bg-rose-100 dark:bg-rose-900/30 px-2 py-0.5 rounded">
                      Disputed
                    </span>
                    <span className="text-[11px] text-[var(--muted-foreground)]">
                      Both claim to be currently true about{" "}
                      <span className="font-medium text-[var(--foreground)]">
                        {pair.unit_a.subject}
                      </span>
                    </span>
                    {isResolvingThis && (
                      <span className="ml-auto text-[11px] text-[var(--muted-foreground)] animate-pulse">
                        Resolving…
                      </span>
                    )}
                  </div>

                  <div className="flex flex-col sm:flex-row gap-4">
                    <UnitCard
                      unit={pair.unit_a}
                      isWinner={
                        pickedWinner === pair.unit_a.id
                          ? true
                          : pickedWinner === pair.unit_b.id
                          ? false
                          : null
                      }
                      onPick={() => resolve(pair.unit_a.id, pair.unit_b.id, pairKey)}
                      resolving={isResolvingThis}
                    />

                    <div className="hidden sm:flex items-center justify-center">
                      <div className="flex flex-col items-center gap-1 text-[var(--muted-foreground)]">
                        <div className="h-px w-px border-l border-dashed border-[var(--border)] h-8" />
                        <span className="text-[10px] uppercase tracking-widest">vs</span>
                        <div className="h-px w-px border-l border-dashed border-[var(--border)] h-8" />
                      </div>
                    </div>
                    <div className="sm:hidden text-center text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] py-1">
                      vs
                    </div>

                    <UnitCard
                      unit={pair.unit_b}
                      isWinner={
                        pickedWinner === pair.unit_b.id
                          ? true
                          : pickedWinner === pair.unit_a.id
                          ? false
                          : null
                      }
                      onPick={() => resolve(pair.unit_b.id, pair.unit_a.id, pairKey)}
                      resolving={isResolvingThis}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
