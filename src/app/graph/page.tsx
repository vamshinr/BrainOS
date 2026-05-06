import Link from "next/link";
import { readState } from "@/lib/store";
import { GraphView } from "@/components/graph-view";
import type { EntityKind } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function GraphPage() {
  const state = await readState();
  const fresh = state.units.filter((u) => !u.stale && !u.supersededBy);

  const entityIndex = new Map<string, { kind: EntityKind; refCount: number }>();
  for (const e of state.entities) {
    entityIndex.set(e.name.toLowerCase(), { kind: e.kind, refCount: 0 });
  }
  for (const u of fresh) {
    for (const name of u.entities) {
      const k = name.toLowerCase();
      const cur = entityIndex.get(k);
      if (cur) cur.refCount += 1;
      else entityIndex.set(k, { kind: "concept", refCount: 1 });
    }
  }

  const nodes = Array.from(entityIndex.entries()).map(([name, info]) => ({
    name: state.entities.find((e) => e.name.toLowerCase() === name)?.name ?? name,
    kind: info.kind,
    refCount: info.refCount,
  }));

  const edgeMap = new Map<string, { a: string; b: string; weight: number }>();
  for (const u of fresh) {
    const names = Array.from(new Set(u.entities.map((n) => n.toLowerCase())));
    for (let i = 0; i < names.length; i++) {
      for (let j = i + 1; j < names.length; j++) {
        const [a, b] = [names[i], names[j]].sort();
        const key = `${a}${b}`;
        const cur = edgeMap.get(key);
        if (cur) cur.weight += 1;
        else edgeMap.set(key, { a, b, weight: 1 });
      }
    }
  }
  const edges = Array.from(edgeMap.values());

  return (
    <div className="px-10 py-10 max-w-6xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Map
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">
        Living map of the company.
      </h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-2xl">
        Entities and their relationships, derived from extracted knowledge.
        Edges represent co-mentions in the same unit; thicker = stronger.
      </p>

      {nodes.length === 0 ? (
        <div className="mt-8 rounded-lg border border-dashed bg-[var(--muted)]/30 px-6 py-10 text-center text-sm">
          No entities yet.{" "}
          <Link href="/ingest" className="underline">
            Ingest something
          </Link>{" "}
          to build the map.
        </div>
      ) : (
        <div className="mt-8 rounded-lg border bg-[var(--card)] dot-grid">
          <GraphView nodes={nodes} edges={edges} />
        </div>
      )}
    </div>
  );
}
