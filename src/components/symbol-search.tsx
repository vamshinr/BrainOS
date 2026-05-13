"use client";

import { useMemo, useState } from "react";
import type { SymbolOccurrence } from "@/lib/store";

export function SymbolSearch({ index }: { index: Record<string, SymbolOccurrence[]> }) {
  const [q, setQ] = useState("");

  const results = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) {
      // Show first 12 alphabetically as a starting view
      return Object.entries(index).slice(0, 12);
    }
    return Object.entries(index)
      .filter(([name]) => name.toLowerCase().includes(query))
      .slice(0, 50);
  }, [q, index]);

  return (
    <div className="rounded-lg border bg-[var(--card)] overflow-hidden">
      <div className="px-3 py-2 border-b bg-[var(--muted)]/30">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Type a function, class, or interface name…"
          className="w-full bg-transparent outline-none text-sm font-mono placeholder:text-[var(--muted-foreground)]"
        />
      </div>
      {results.length === 0 ? (
        <div className="px-4 py-6 text-center text-xs text-[var(--muted-foreground)]">
          No symbols matched.
        </div>
      ) : (
        <ul className="max-h-[40vh] overflow-y-auto divide-y divide-[var(--muted)]/40">
          {results.map(([name, occurrences]) => (
            <li key={name} className="px-3 py-2 text-xs">
              <div className="flex items-baseline gap-2">
                <span className="font-mono font-medium">{name}</span>
                <span className="text-[10px] uppercase tracking-wide text-[var(--muted-foreground)]">
                  {occurrences[0].kind}
                </span>
                {occurrences.length > 1 && (
                  <span className="text-[10px] text-amber-600 dark:text-amber-400">
                    {occurrences.length}× (ambiguous)
                  </span>
                )}
              </div>
              <ul className="mt-1 ml-3 space-y-0.5">
                {occurrences.slice(0, 5).map((o, i) => (
                  <li
                    key={i}
                    className="flex items-baseline gap-2 text-[11px] text-[var(--muted-foreground)] font-mono"
                  >
                    <span className="truncate flex-1">{o.path}</span>
                    {o.parent && <span className="opacity-70">in {o.parent}</span>}
                    <span className="tabular-nums">L{o.line}</span>
                  </li>
                ))}
                {occurrences.length > 5 && (
                  <li className="text-[10px] text-[var(--muted-foreground)] ml-2">
                    … +{occurrences.length - 5} more
                  </li>
                )}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
