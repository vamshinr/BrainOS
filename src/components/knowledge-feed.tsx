"use client";

import { useMemo, useState } from "react";
import { formatDate } from "@/lib/utils";
import type { UnitKind } from "@/lib/types";
import type { Unit } from "@/lib/store";

const KIND_LABELS: Record<UnitKind, string> = {
  fact: "fact",
  process: "process",
  decision: "decision",
  ownership: "ownership",
  definition: "definition",
  policy: "policy",
  gotcha: "gotcha",
};

const KIND_TINT: Record<UnitKind, string> = {
  fact: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  process: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  decision: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  ownership: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  definition: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  policy: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
  gotcha: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
};

type Filter = "all" | UnitKind;

export function KnowledgeFeed({ units }: { units: Unit[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [disputedOnly, setDisputedOnly] = useState(false);
  const [query, setQuery] = useState("");

  const byKind = useMemo(() => {
    const m: Record<string, number> = {};
    for (const u of units) m[u.kind] = (m[u.kind] ?? 0) + 1;
    return m;
  }, [units]);

  const disputedCount = useMemo(
    () => units.filter((u) => u.disputed).length,
    [units],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return units.filter((u) => {
      if (filter !== "all" && u.kind !== filter) return false;
      if (disputedOnly && !u.disputed) return false;
      if (q && !u.statement.toLowerCase().includes(q) && !u.subject.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [units, filter, disputedOnly, query]);

  const kindsInUse = (Object.keys(KIND_LABELS) as UnitKind[]).filter((k) => (byKind[k] ?? 0) > 0);

  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5 mb-3">
        <FilterChip
          active={filter === "all"}
          onClick={() => setFilter("all")}
          label="all"
          count={units.length}
        />
        {kindsInUse.map((k) => (
          <FilterChip
            key={k}
            active={filter === k}
            onClick={() => setFilter(k)}
            label={KIND_LABELS[k]}
            count={byKind[k] ?? 0}
            tint={KIND_TINT[k]}
          />
        ))}
        <div className="grow" />
        {disputedCount > 0 && (
          <button
            type="button"
            onClick={() => setDisputedOnly((v) => !v)}
            className={`rounded-full px-2.5 py-1 text-[11px] font-medium border transition-colors ${
              disputedOnly
                ? "border-red-300 bg-red-50 text-red-700 dark:bg-red-950/40 dark:border-red-800 dark:text-red-300"
                : "border-transparent text-[var(--muted-foreground)] hover:bg-[var(--card)]"
            }`}
          >
            <span className="mr-1">⚠</span>
            {disputedOnly ? "disputed only" : `${disputedCount} disputed`}
          </button>
        )}
      </div>

      <div className="mb-4">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search statements or subjects…"
          className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm placeholder:text-[var(--muted-foreground)]"
        />
      </div>

      {visible.length === 0 ? (
        <div className="rounded-md border bg-[var(--card)] px-4 py-6 text-sm text-[var(--muted-foreground)] text-center">
          No units match these filters.
        </div>
      ) : (
        <ul className="space-y-2">
          {visible.map((u) => (
            <li
              key={u.id}
              className="rounded-lg border bg-[var(--card)] px-4 py-3 hover:border-[var(--accent)]/40 transition-colors"
            >
              <div className="flex items-start gap-3">
                <span
                  className={`mt-0.5 inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${KIND_TINT[u.kind]}`}
                >
                  {KIND_LABELS[u.kind]}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start gap-2">
                    <div className="text-sm leading-snug flex-1">{u.statement}</div>
                    {u.disputed && (
                      <span
                        title={`Conflicts with ${u.conflictsWith?.length ?? 0} other unit(s)`}
                        className="shrink-0 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300 border border-red-200 dark:border-red-800"
                      >
                        <span className="size-1.5 rounded-full bg-red-500 inline-block animate-pulse" />
                        Disputed
                      </span>
                    )}
                  </div>
                  <div className="mt-1.5 flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
                    <span>subject: {u.subject}</span>
                    <span>·</span>
                    <span>conf {u.confidence.toFixed(2)}</span>
                    <span>·</span>
                    <span>{formatDate(u.createdAt)}</span>
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  label,
  count,
  tint,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  tint?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors border ${
        active
          ? "border-[var(--foreground)] bg-[var(--foreground)] text-[var(--background)]"
          : tint
            ? `${tint} border-transparent hover:opacity-80`
            : "border-transparent text-[var(--muted-foreground)] hover:bg-[var(--card)]"
      }`}
    >
      {label}
      <span className={`ml-1.5 tabular-nums ${active ? "opacity-70" : "opacity-60"}`}>
        {count}
      </span>
    </button>
  );
}
