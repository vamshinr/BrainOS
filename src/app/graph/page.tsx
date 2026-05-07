import Link from "next/link";
import { readState } from "@/lib/store";
import { GraphView } from "@/components/graph-view";
import type { EntityKind } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function GraphPage() {
  const state = await readState();
  const fresh = state.units.filter((u) => !u.stale && !u.supersededBy);
  const rels = state.relationships ?? [];

  // Build entity index with ref counts
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

  // Prefer explicit relationships; fall back to co-mention edges
  const explicitEdges = rels.map((r) => ({
    a: r.from,
    b: r.to,
    label: r.relation,
    weight: Math.round(r.confidence * 3),
  }));

  const coMentionMap = new Map<string, { a: string; b: string; weight: number }>();
  if (explicitEdges.length === 0) {
    for (const u of fresh) {
      const names = Array.from(new Set(u.entities.map((n) => n.toLowerCase())));
      for (let i = 0; i < names.length; i++) {
        for (let j = i + 1; j < names.length; j++) {
          const [a, b] = [names[i], names[j]].sort();
          const key = `${a}\0${b}`;
          const cur = coMentionMap.get(key);
          if (cur) cur.weight += 1;
          else coMentionMap.set(key, { a, b, weight: 1 });
        }
      }
    }
  }

  const edges =
    explicitEdges.length > 0
      ? explicitEdges
      : Array.from(coMentionMap.values()).map((e) => ({ ...e, label: undefined }));

  return (
    <div className="px-10 py-10 max-w-6xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Map
      </div>
      <div className="flex items-end justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">
          Company knowledge graph.
        </h1>
        <div className="text-[11px] text-[var(--muted-foreground)] space-x-2">
          <span>{nodes.length} entities</span>
          <span>·</span>
          <span>{edges.length} {rels.length > 0 ? "relationships" : "co-mention edges"}</span>
        </div>
      </div>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-2xl">
        {rels.length > 0
          ? "Explicit relationships extracted from company knowledge — who owns what, what uses what, what governs what. This is what separates BrainOS from a plain RAG wrapper."
          : "Entities connected by co-mention in knowledge units. Ingest more content to build explicit directional relationships."}
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
          <GraphView nodes={nodes} edges={edges} hasExplicitRels={rels.length > 0} />
        </div>
      )}

      {/* Relationship list below graph */}
      {rels.length > 0 && (
        <section className="mt-8">
          <h2 className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
            Relationship index
          </h2>
          <div className="rounded-lg border bg-[var(--card)] overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-[var(--muted)]/30 text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
                  <th className="text-left px-4 py-2">From</th>
                  <th className="text-left px-4 py-2">Relation</th>
                  <th className="text-left px-4 py-2">To</th>
                  <th className="text-right px-4 py-2">Conf</th>
                </tr>
              </thead>
              <tbody>
                {rels.slice(0, 50).map((r) => (
                  <tr key={r.id} className="border-b last:border-0 hover:bg-[var(--muted)]/20">
                    <td className="px-4 py-2 font-medium">{r.from}</td>
                    <td className="px-4 py-2 font-mono text-[var(--muted-foreground)] text-[11px]">
                      {r.relation}
                    </td>
                    <td className="px-4 py-2 font-medium">{r.to}</td>
                    <td className="px-4 py-2 text-right font-mono text-[11px] text-[var(--muted-foreground)]">
                      {r.confidence.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rels.length > 50 && (
              <div className="px-4 py-2 text-[11px] text-[var(--muted-foreground)] border-t">
                Showing 50 of {rels.length} relationships
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
