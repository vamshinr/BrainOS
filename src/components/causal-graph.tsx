"use client";

import { useMemo, useState } from "react";
import type { GraphDump, MnemEvent } from "@/lib/mnemosyne";
import { relationColor } from "@/lib/mnemosyne";

// A causal timeline: events placed left→right by time, with cause→effect arcs
// above the axis (every edge necessarily points forward in time).
const COL = 190; // horizontal spacing between events
const PAD_X = 60;
const AXIS_Y = 260;
const NODE_R = 7;

function truncate(s: string, n = 30): string {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

export function CausalGraph({ data }: { data: GraphDump }) {
  const [hover, setHover] = useState<string | null>(null);

  const { nodes, edges, width } = useMemo(() => {
    const sorted = [...data.events].sort(
      (a, b) => new Date(a.occurred_at).getTime() - new Date(b.occurred_at).getTime(),
    );
    const pos = new Map<string, { x: number; y: number; ev: MnemEvent; idx: number }>();
    sorted.forEach((ev, i) => {
      pos.set(ev.id, { x: PAD_X + i * COL, y: AXIS_Y, ev, idx: i });
    });
    const edges = data.edges
      .map((e) => {
        const a = pos.get(e.cause_id);
        const b = pos.get(e.effect_id);
        if (!a || !b) return null;
        return { edge: e, a, b, span: Math.abs(b.idx - a.idx) };
      })
      .filter((x): x is NonNullable<typeof x> => x !== null);
    return {
      nodes: [...pos.values()],
      edges,
      width: PAD_X * 2 + Math.max(0, sorted.length - 1) * COL,
    };
  }, [data]);

  if (!nodes.length) return null;

  const connected = (id: string) =>
    hover === null ||
    hover === id ||
    edges.some(
      (e) =>
        (e.edge.cause_id === hover && e.edge.effect_id === id) ||
        (e.edge.effect_id === hover && e.edge.cause_id === id),
    );

  return (
    <div className="overflow-x-auto rounded-md border bg-[var(--card)]">
      <svg width={Math.max(width, 600)} height={AXIS_Y + 120} className="min-w-full">
        <defs>
          {Object.entries({ caused: "#ef4444", triggered: "#f97316", led_to: "#eab308", enabled: "#22c55e", supersedes: "#8b5cf6", default: "#64748b" }).map(
            ([k, c]) => (
              <marker
                key={k}
                id={`arrow-${k}`}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 0 L 10 5 L 0 10 z" fill={c} />
              </marker>
            ),
          )}
        </defs>

        {/* time axis */}
        <line x1={PAD_X - 20} y1={AXIS_Y} x2={width - PAD_X + 40} y2={AXIS_Y} stroke="var(--border)" />

        {/* edges (arcs above the axis) */}
        {edges.map(({ edge, a, b, span }) => {
          const arc = 40 + span * 26;
          const mx = (a.x + b.x) / 2;
          const dim = !(connected(edge.cause_id) && connected(edge.effect_id));
          const key = ["caused", "triggered", "led_to", "enabled", "supersedes"].includes(edge.relation)
            ? edge.relation
            : "default";
          return (
            <path
              key={edge.id}
              d={`M ${a.x} ${a.y - NODE_R} Q ${mx} ${a.y - arc} ${b.x} ${b.y - NODE_R}`}
              fill="none"
              stroke={relationColor(edge.relation)}
              strokeWidth={1 + edge.confidence * 1.5}
              strokeOpacity={dim ? 0.12 : 0.35 + edge.confidence * 0.5}
              markerEnd={`url(#arrow-${key})`}
            />
          );
        })}

        {/* nodes */}
        {nodes.map(({ x, y, ev }) => {
          const dim = !connected(ev.id);
          return (
            <g
              key={ev.id}
              opacity={dim ? 0.25 : 1}
              onMouseEnter={() => setHover(ev.id)}
              onMouseLeave={() => setHover(null)}
              style={{ cursor: "default" }}
            >
              <circle cx={x} cy={y} r={NODE_R} fill="var(--foreground)" />
              <text x={x} y={y + 24} textAnchor="middle" className="fill-[var(--muted-foreground)]" fontSize="10" fontFamily="monospace">
                {new Date(ev.occurred_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
              </text>
              <text x={x} y={y + 42} textAnchor="middle" className="fill-[var(--foreground)]" fontSize="11">
                {truncate(ev.summary)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
