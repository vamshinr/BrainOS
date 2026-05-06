"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

type Event =
  | { type: "start"; total: number }
  | { type: "source:start"; index: number; title: string; kind: string }
  | {
      type: "source:done";
      index: number;
      title: string;
      units: number;
      entities: number;
    }
  | { type: "source:error"; index: number; error: string }
  | { type: "done"; totalUnits: number; totalEntities: number };

export function SeedButton() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<{
    current: string | null;
    done: number;
    total: number;
    units: number;
    entities: number;
  }>({ current: null, done: 0, total: 0, units: 0, entities: 0 });
  const [err, setErr] = useState<string | null>(null);

  async function seed() {
    setLoading(true);
    setErr(null);
    setProgress({ current: null, done: 0, total: 0, units: 0, entities: 0 });
    try {
      const res = await fetch("/api/seed", { method: "POST" });
      if (!res.ok || !res.body) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.error ?? `HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev: Event = JSON.parse(line);
          if (ev.type === "start") {
            setProgress((p) => ({ ...p, total: ev.total }));
          } else if (ev.type === "source:start") {
            setProgress((p) => ({ ...p, current: ev.title }));
          } else if (ev.type === "source:done") {
            setProgress((p) => ({
              ...p,
              done: p.done + 1,
              units: p.units + ev.units,
              entities: p.entities + ev.entities,
              current: null,
            }));
          } else if (ev.type === "source:error") {
            setErr(`Source ${ev.index}: ${ev.error}`);
          }
        }
      }
      router.refresh();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-stretch gap-1.5">
      <button
        onClick={seed}
        disabled={loading}
        className="text-sm text-center rounded-md border px-3 py-2 hover:bg-[var(--muted)] disabled:opacity-50"
      >
        {loading
          ? `Seeding ${progress.done}/${progress.total || 5}…`
          : "Seed with example company"}
      </button>
      {loading && progress.current && (
        <div className="text-[11px] text-[var(--muted-foreground)] truncate">
          Extracting: {progress.current}
        </div>
      )}
      {loading && progress.units > 0 && (
        <div className="text-[11px] text-[var(--muted-foreground)]">
          {progress.units} units · {progress.entities} entities so far
        </div>
      )}
      {err && <div className="text-[11px] text-red-600">{err}</div>}
    </div>
  );
}
