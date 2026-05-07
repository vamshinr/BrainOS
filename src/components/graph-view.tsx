"use client";

import { useMemo, useState } from "react";
import type { EntityKind } from "@/lib/types";

type Node = { name: string; kind: EntityKind; refCount: number };
type Edge = { a: string; b: string; weight: number; label?: string };

const KIND_COLOR: Record<EntityKind, string> = {
  person:   "#7c3aed",
  team:     "#2563eb",
  system:   "#0891b2",
  product:  "#0d9488",
  process:  "#65a30d",
  concept:  "#a16207",
  tool:     "#c2410c",
  customer: "#db2777",
};

// Quadratic bezier path + arrowhead for directed edges
function directedPath(
  x1: number, y1: number,
  x2: number, y2: number,
  r1: number, r2: number,
): { path: string; labelX: number; labelY: number } {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  // Start/end at node perimeter
  const sx = x1 + (dx / len) * r1;
  const sy = y1 + (dy / len) * r1;
  const ex = x2 - (dx / len) * (r2 + 6); // 6px before end for arrowhead
  const ey = y2 - (dy / len) * (r2 + 6);
  // Slight curve
  const bend = Math.min(len * 0.12, 20);
  const cx = (sx + ex) / 2 - (dy / len) * bend;
  const cy = (sy + ey) / 2 + (dx / len) * bend;
  const path = `M ${sx} ${sy} Q ${cx} ${cy} ${ex} ${ey}`;
  return { path, labelX: cx, labelY: cy };
}

export function GraphView({
  nodes,
  edges,
  hasExplicitRels = false,
}: {
  nodes: Node[];
  edges: Edge[];
  hasExplicitRels?: boolean;
}) {
  const W = 1000;
  const H = 600;
  const [hover, setHover] = useState<string | null>(null);

  const positioned = useMemo(() => {
    if (nodes.length === 0) return [];
    const cx = W / 2;
    const cy = H / 2;
    const byKind = new Map<EntityKind, Node[]>();
    for (const n of nodes) {
      const list = byKind.get(n.kind) ?? [];
      list.push(n);
      byKind.set(n.kind, list);
    }
    const kinds = Array.from(byKind.keys());
    const out: { node: Node; x: number; y: number; r: number }[] = [];
    kinds.forEach((kind, ki) => {
      const ring = byKind.get(kind)!;
      const maxRef = Math.max(1, ...nodes.map((n) => n.refCount));
      const radius = 80 + ki * 90;
      ring.forEach((n, ni) => {
        const angle =
          (ni / Math.max(ring.length, 1)) * Math.PI * 2 + (ki * Math.PI) / 7;
        const r = 8 + (n.refCount / maxRef) * 14;
        out.push({ node: n, x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius, r });
      });
    });
    return out;
  }, [nodes]);

  const posIndex = useMemo(() => {
    const m = new Map<string, { x: number; y: number; r: number; node: Node }>();
    for (const p of positioned) m.set(p.node.name.toLowerCase(), p);
    return m;
  }, [positioned]);

  const maxWeight = Math.max(1, ...edges.map((e) => e.weight));

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-[580px]">
        <defs>
          <marker id="arrow" markerWidth="6" markerHeight="6" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="var(--accent)" fillOpacity="0.7" />
          </marker>
          <marker id="arrow-dim" markerWidth="6" markerHeight="6" refX="6" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill="currentColor" fillOpacity="0.15" />
          </marker>
        </defs>

        {/* Edges */}
        <g>
          {edges.map((e, i) => {
            const a = posIndex.get(e.a.toLowerCase());
            const b = posIndex.get(e.b.toLowerCase());
            if (!a || !b) return null;
            const dimmed = hover && hover !== a.node.name && hover !== b.node.name;
            const opacity = dimmed ? 0.06 : 0.25 + (e.weight / maxWeight) * 0.55;

            if (hasExplicitRels && e.label) {
              const { path, labelX, labelY } = directedPath(a.x, a.y, b.x, b.y, a.r, b.r);
              return (
                <g key={i}>
                  <path
                    d={path}
                    fill="none"
                    stroke={dimmed ? "currentColor" : "var(--accent)"}
                    strokeOpacity={opacity}
                    strokeWidth={1.5}
                    markerEnd={dimmed ? "url(#arrow-dim)" : "url(#arrow)"}
                    className={dimmed ? "text-[var(--muted-foreground)]" : ""}
                  />
                  {!dimmed && (
                    <text
                      x={labelX}
                      y={labelY - 6}
                      textAnchor="middle"
                      fontSize={9}
                      fill="var(--muted-foreground)"
                      className="select-none pointer-events-none"
                    >
                      {e.label}
                    </text>
                  )}
                </g>
              );
            }

            // Co-mention fallback — undirected
            return (
              <line
                key={i}
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke="currentColor"
                strokeOpacity={dimmed ? 0.04 : opacity}
                strokeWidth={1 + (e.weight / maxWeight) * 3}
                className="text-[var(--muted-foreground)]"
              />
            );
          })}
        </g>

        {/* Nodes */}
        <g>
          {positioned.map((p) => {
            const dimmed = hover && hover !== p.node.name;
            const color = KIND_COLOR[p.node.kind];
            return (
              <g
                key={p.node.name}
                transform={`translate(${p.x},${p.y})`}
                onMouseEnter={() => setHover(p.node.name)}
                onMouseLeave={() => setHover(null)}
                style={{ cursor: "pointer", opacity: dimmed ? 0.25 : 1 }}
              >
                {hover === p.node.name && (
                  <circle r={p.r + 6} fill={color} fillOpacity={0.15} />
                )}
                <circle r={p.r} fill={color} fillOpacity={0.9} stroke="white" strokeWidth={2} />
                <text
                  y={p.r + 13}
                  textAnchor="middle"
                  fontSize={11}
                  fontWeight={hover === p.node.name ? "600" : "400"}
                  className="fill-current"
                  style={{ pointerEvents: "none" }}
                >
                  {p.node.name}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Legend */}
      <div className="absolute top-3 left-3 rounded-md border bg-[var(--background)]/90 backdrop-blur px-3 py-2 text-[11px]">
        <div className="font-medium mb-1.5">
          {hasExplicitRels ? "Knowledge graph — directed relationships" : "Co-mention graph"}
        </div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
          {(Object.keys(KIND_COLOR) as EntityKind[]).map((k) => (
            <div key={k} className="flex items-center gap-1.5">
              <span className="size-2.5 rounded-full inline-block" style={{ background: KIND_COLOR[k] }} />
              <span>{k}</span>
            </div>
          ))}
        </div>
        {hasExplicitRels && (
          <div className="mt-2 pt-2 border-t flex items-center gap-1.5 text-[var(--muted-foreground)]">
            <span className="text-[var(--accent)]">→</span>
            <span>directed relationship edge</span>
          </div>
        )}
      </div>
    </div>
  );
}
