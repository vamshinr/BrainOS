"use client";

import { useMemo, useState } from "react";
import type { EntityKind } from "@/lib/types";

type Node = { name: string; kind: EntityKind; refCount: number };
type Edge = { a: string; b: string; weight: number };

const KIND_COLOR: Record<EntityKind, string> = {
  person: "#7c3aed",
  team: "#2563eb",
  system: "#0891b2",
  product: "#0d9488",
  process: "#65a30d",
  concept: "#a16207",
  tool: "#c2410c",
  customer: "#db2777",
};

export function GraphView({ nodes, edges }: { nodes: Node[]; edges: Edge[] }) {
  const W = 1000;
  const H = 600;
  const [hover, setHover] = useState<string | null>(null);

  const positioned = useMemo(() => {
    if (nodes.length === 0) return [];
    const cx = W / 2;
    const cy = H / 2;
    // group by kind into concentric rings for clarity
    const byKind = new Map<EntityKind, Node[]>();
    for (const n of nodes) {
      const list = byKind.get(n.kind) ?? [];
      list.push(n);
      byKind.set(n.kind, list);
    }
    const kinds = Array.from(byKind.keys());
    const out: { node: Node; x: number; y: number }[] = [];
    kinds.forEach((kind, ki) => {
      const ring = byKind.get(kind)!;
      const radius = 70 + ki * 80;
      ring.forEach((n, ni) => {
        const angle =
          (ni / Math.max(ring.length, 1)) * Math.PI * 2 + (ki * Math.PI) / 7;
        out.push({
          node: n,
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
        });
      });
    });
    return out;
  }, [nodes]);

  const posIndex = useMemo(() => {
    const m = new Map<string, { x: number; y: number; node: Node }>();
    for (const p of positioned) m.set(p.node.name.toLowerCase(), p);
    return m;
  }, [positioned]);

  const maxWeight = Math.max(1, ...edges.map((e) => e.weight));
  const maxRef = Math.max(1, ...nodes.map((n) => n.refCount));

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[600px]">
        <g>
          {edges.map((e, i) => {
            const a = posIndex.get(e.a);
            const b = posIndex.get(e.b);
            if (!a || !b) return null;
            const dimmed =
              hover && hover !== a.node.name && hover !== b.node.name;
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke="currentColor"
                strokeOpacity={dimmed ? 0.05 : 0.2 + (e.weight / maxWeight) * 0.5}
                strokeWidth={1 + (e.weight / maxWeight) * 3}
                className="text-[var(--muted-foreground)]"
              />
            );
          })}
        </g>
        <g>
          {positioned.map((p) => {
            const r = 8 + (p.node.refCount / maxRef) * 14;
            const dimmed = hover && hover !== p.node.name;
            return (
              <g
                key={p.node.name}
                transform={`translate(${p.x},${p.y})`}
                onMouseEnter={() => setHover(p.node.name)}
                onMouseLeave={() => setHover(null)}
                style={{ cursor: "pointer", opacity: dimmed ? 0.3 : 1 }}
              >
                <circle
                  r={r}
                  fill={KIND_COLOR[p.node.kind]}
                  fillOpacity={0.9}
                  stroke="white"
                  strokeWidth={2}
                />
                <text
                  y={r + 12}
                  textAnchor="middle"
                  className="fill-current text-[11px] font-medium"
                  style={{ pointerEvents: "none" }}
                >
                  {p.node.name}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="absolute top-3 left-3 rounded-md border bg-[var(--background)]/90 backdrop-blur px-3 py-2 text-[11px]">
        <div className="font-medium mb-1.5">Entity types</div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
          {(Object.keys(KIND_COLOR) as EntityKind[]).map((k) => (
            <div key={k} className="flex items-center gap-1.5">
              <span
                className="size-2.5 rounded-full inline-block"
                style={{ background: KIND_COLOR[k] }}
              />
              <span>{k}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
