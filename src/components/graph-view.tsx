"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EntityKind } from "@/lib/types";

export type SourceTag = "slack" | "doc";

type Node = {
  name: string;
  kind: EntityKind;
  refCount: number;
  /** Tags of source kinds that contributed evidence to units mentioning
   *  this entity. Used by the docs/slack filter pills. */
  sources?: SourceTag[];
};
type Edge = { a: string; b: string; weight: number; label?: string };

const KIND_COLOR: Record<string, string> = {
  person:   "#a78bfa",
  team:     "#60a5fa",
  system:   "#22d3ee",
  product:  "#34d399",
  process:  "#a3e635",
  concept:  "#fbbf24",
  tool:     "#fb923c",
  customer: "#f472b6",
};

const KIND_LABEL: Record<string, string> = {
  person: "People", team: "Teams", system: "Systems",
  product: "Products", process: "Processes", concept: "Concepts",
  tool: "Tools", customer: "Customers",
};

const W = 1100, H = 740;

// ── Force-directed simulation (no external deps) ──────────────────────────────

function buildLayout(nodes: Node[], edges: Edge[]): Array<{ x: number; y: number }> {
  if (nodes.length === 0) return [];

  const nameIdx = new Map(nodes.map((n, i) => [n.name.toLowerCase(), i]));
  const edgeIdxs: [number, number][] = [];
  for (const e of edges) {
    const a = nameIdx.get(e.a.toLowerCase()), b = nameIdx.get(e.b.toLowerCase());
    if (a !== undefined && b !== undefined) edgeIdxs.push([a, b]);
  }

  const idealLen = Math.max(100, Math.min(260, 550 / Math.sqrt(nodes.length + 1)));

  // Start on concentric circles by kind
  const kindOrder = ["person", "team", "system", "product", "process", "concept", "tool", "customer"];
  const byKind = new Map<string, number[]>();
  nodes.forEach((n, i) => {
    const k = n.kind ?? "concept";
    if (!byKind.has(k)) byKind.set(k, []);
    byKind.get(k)!.push(i);
  });

  const pos: Array<{ x: number; y: number; vx: number; vy: number }> = new Array(nodes.length);
  let ring = 0;
  for (const k of kindOrder) {
    const idxs = byKind.get(k) ?? [];
    if (!idxs.length) continue;
    const r = 80 + ring * 110;
    idxs.forEach((i, j) => {
      const a = (j / Math.max(idxs.length, 1)) * Math.PI * 2 + ring * 0.7;
      pos[i] = { x: W / 2 + Math.cos(a) * r, y: H / 2 + Math.sin(a) * r, vx: 0, vy: 0 };
    });
    ring++;
  }
  // Fill any that weren't assigned
  nodes.forEach((_, i) => {
    if (!pos[i]) pos[i] = { x: W / 2, y: H / 2, vx: 0, vy: 0 };
  });

  for (let iter = 0; iter < 320; iter++) {
    // Repulsion (all pairs)
    for (let i = 0; i < pos.length; i++) {
      for (let j = i + 1; j < pos.length; j++) {
        const dx = pos[i].x - pos[j].x, dy = pos[i].y - pos[j].y;
        const d2 = dx * dx + dy * dy + 1;
        const d = Math.sqrt(d2);
        const f = 6500 / d2;
        pos[i].vx += (dx / d) * f; pos[i].vy += (dy / d) * f;
        pos[j].vx -= (dx / d) * f; pos[j].vy -= (dy / d) * f;
      }
    }
    // Spring attraction
    for (const [ai, bi] of edgeIdxs) {
      const dx = pos[bi].x - pos[ai].x, dy = pos[bi].y - pos[ai].y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - idealLen) * 0.045;
      const fx = (dx / d) * f, fy = (dy / d) * f;
      pos[ai].vx += fx; pos[ai].vy += fy;
      pos[bi].vx -= fx; pos[bi].vy -= fy;
    }
    // Center gravity + damping
    const decay = 0.84;
    for (const p of pos) {
      p.vx += (W / 2 - p.x) * 0.004;
      p.vy += (H / 2 - p.y) * 0.004;
      p.vx *= decay; p.vy *= decay;
      p.x = Math.max(70, Math.min(W - 70, p.x + p.vx));
      p.y = Math.max(70, Math.min(H - 70, p.y + p.vy));
    }
  }

  return pos;
}

// ── Edge path (quadratic bezier with arrowhead gap) ───────────────────────────

function edgePath(x1: number, y1: number, x2: number, y2: number, r1: number, r2: number) {
  const dx = x2 - x1, dy = y2 - y1;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  const sx = x1 + (dx / len) * r1, sy = y1 + (dy / len) * r1;
  const ex = x2 - (dx / len) * (r2 + 10), ey = y2 - (dy / len) * (r2 + 10);
  const bend = Math.sign(dx * dy + 0.001) * Math.min(len * 0.18, 36);
  const qx = (sx + ex) / 2 - (dy / len) * bend;
  const qy = (sy + ey) / 2 + (dx / len) * bend;
  return { d: `M${sx},${sy} Q${qx},${qy} ${ex},${ey}`, lx: qx, ly: qy };
}

// ── Main component ────────────────────────────────────────────────────────────

export function GraphView({
  nodes, edges, hasExplicitRels = false,
}: { nodes: Node[]; edges: Edge[]; hasExplicitRels?: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // zoom / pan transform
  const [tf, setTf] = useState({ x: 0, y: 0, s: 1 });
  const tfRef = useRef(tf);
  useEffect(() => { tfRef.current = tf; }, [tf]);

  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [isFull, setIsFull] = useState(false);

  // Source-type filter chips. Empty set OR both flipped on = "show all"
  // (no dimming). Picking just one bucket dims everything that didn't come
  // from that source.
  const [sourceFilter, setSourceFilter] = useState<Set<SourceTag>>(new Set());
  const filteringBySource = sourceFilter.size > 0 && sourceFilter.size < 2;

  const toggleSourceFilter = useCallback((tag: SourceTag) => {
    setSourceFilter((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) next.delete(tag);
      else next.add(tag);
      return next;
    });
  }, []);

  // Per-entity: does this node belong to the active source filter? When the
  // filter is inactive (size 0 or 2), every node is considered "in".
  const nodeInFilter = useCallback(
    (n: Node) => {
      if (!filteringBySource) return true;
      const tags = n.sources ?? [];
      for (const t of tags) if (sourceFilter.has(t)) return true;
      return false;
    },
    [filteringBySource, sourceFilter],
  );

  const isPanning = useRef(false);
  const didMove = useRef(false);
  const panOrigin = useRef({ mx: 0, my: 0, ox: 0, oy: 0 });

  // Force layout — only recalculates when node count or edge count changes
  const nodeKey = useMemo(() => nodes.map(n => n.name).join("|"), [nodes]);
  const layout = useMemo(
    () => buildLayout(nodes, edges),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nodeKey, edges.length],
  );

  // Per-node degree for radius sizing
  const degree = useMemo(() => {
    const d = new Map<string, number>();
    for (const e of edges) {
      const ak = e.a.toLowerCase(), bk = e.b.toLowerCase();
      d.set(ak, (d.get(ak) ?? 0) + 1);
      d.set(bk, (d.get(bk) ?? 0) + 1);
    }
    return d;
  }, [edges]);
  const maxDeg = Math.max(1, ...degree.values());

  const pnodes = useMemo(() => nodes.map((n, i) => ({
    ...n,
    x: layout[i]?.x ?? W / 2,
    y: layout[i]?.y ?? H / 2,
    r: 10 + ((degree.get(n.name.toLowerCase()) ?? 0) / maxDeg) * 14,
    color: KIND_COLOR[n.kind] ?? "#888",
  })), [nodes, layout, degree, maxDeg]);

  const pidx = useMemo(() => {
    const m = new Map<string, typeof pnodes[0]>();
    for (const p of pnodes) m.set(p.name.toLowerCase(), p);
    return m;
  }, [pnodes]);

  const active = selected ?? hovered;
  const connSet = useMemo(() => {
    if (!active) return null;
    const s = new Set([active.toLowerCase()]);
    for (const e of edges) {
      if (e.a.toLowerCase() === active.toLowerCase()) s.add(e.b.toLowerCase());
      if (e.b.toLowerCase() === active.toLowerCase()) s.add(e.a.toLowerCase());
    }
    return s;
  }, [active, edges]);

  // ── Interactions ──────────────────────────────────────────────────────────

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const rect = svgRef.current!.getBoundingClientRect();
    const mx = ((e.clientX - rect.left) / rect.width) * W;
    const my = ((e.clientY - rect.top) / rect.height) * H;
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    setTf(t => {
      const ns = Math.max(0.12, Math.min(7, t.s * factor));
      const ratio = ns / t.s;
      return { x: mx - (mx - t.x) * ratio, y: my - (my - t.y) * ratio, s: ns };
    });
  }, []);

  const onMouseDown = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    isPanning.current = true;
    didMove.current = false;
    const t = tfRef.current;
    panOrigin.current = { mx: e.clientX, my: e.clientY, ox: t.x, oy: t.y };
  }, []);

  const onMouseMove = useCallback((e: React.MouseEvent<SVGSVGElement>) => {
    if (!isPanning.current) return;
    const dx = e.clientX - panOrigin.current.mx;
    const dy = e.clientY - panOrigin.current.my;
    if (!didMove.current && Math.sqrt(dx * dx + dy * dy) < 4) return;
    didMove.current = true;
    const rect = svgRef.current!.getBoundingClientRect();
    setTf(t => ({
      ...t,
      x: panOrigin.current.ox + dx * (W / rect.width),
      y: panOrigin.current.oy + dy * (H / rect.height),
    }));
  }, []);

  const onMouseUp = useCallback(() => { isPanning.current = false; }, []);

  const fitScreen = useCallback(() => {
    if (!pnodes.length) { setTf({ x: 0, y: 0, s: 1 }); return; }
    const xs = pnodes.map(n => n.x), ys = pnodes.map(n => n.y);
    const pad = 60;
    const x0 = Math.min(...xs) - pad, x1 = Math.max(...xs) + pad;
    const y0 = Math.min(...ys) - pad, y1 = Math.max(...ys) + pad;
    const scale = Math.min(W / (x1 - x0), H / (y1 - y0), 2.5);
    setTf({ x: W / 2 - ((x0 + x1) / 2) * scale, y: H / 2 - ((y0 + y1) / 2) * scale, s: scale });
  }, [pnodes]);

  const toggleFull = useCallback(() => {
    if (!document.fullscreenElement) containerRef.current?.requestFullscreen();
    else document.exitFullscreen();
  }, []);

  useEffect(() => {
    const h = () => setIsFull(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", h);
    return () => document.removeEventListener("fullscreenchange", h);
  }, []);

  // ── Derived display data ──────────────────────────────────────────────────

  const presentKinds = useMemo(() => {
    const ks = new Set(nodes.map(n => n.kind));
    return Object.keys(KIND_COLOR).filter(k => ks.has(k as EntityKind));
  }, [nodes]);

  const selConns = useMemo(() =>
    !selected ? [] : edges.filter(e =>
      e.a.toLowerCase() === selected.toLowerCase() ||
      e.b.toLowerCase() === selected.toLowerCase(),
    ), [selected, edges]);

  const selNode = pnodes.find(n => n.name.toLowerCase() === selected?.toLowerCase());

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div
      ref={containerRef}
      className={`relative overflow-hidden rounded-lg border bg-[var(--card)] ${
        isFull ? "fixed inset-0 z-50 rounded-none border-none" : ""
      }`}
      style={{ height: isFull ? "100dvh" : 700 }}
    >
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-full cursor-grab active:cursor-grabbing select-none"
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
        onClick={() => { if (!didMove.current) setSelected(null); }}
      >
        <defs>
          <filter id="glow-md" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="5" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="glow-lg" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="10" result="b" />
            <feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <marker id="arr" markerWidth="9" markerHeight="9" refX="8" refY="3.5" orient="auto">
            <path d="M0,0 L9,3.5 L0,7 Z" fill="var(--accent)" fillOpacity="0.85" />
          </marker>
          <marker id="arr-hi" markerWidth="9" markerHeight="9" refX="8" refY="3.5" orient="auto">
            <path d="M0,0 L9,3.5 L0,7 Z" fill="white" />
          </marker>
          <marker id="arr-dim" markerWidth="9" markerHeight="9" refX="8" refY="3.5" orient="auto">
            <path d="M0,0 L9,3.5 L0,7 Z" fill="currentColor" fillOpacity="0.08" />
          </marker>
          <pattern id="bg-grid" x="0" y="0" width="32" height="32" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="0.9" fill="currentColor" fillOpacity="0.06" />
          </pattern>
        </defs>

        {/* Canvas background */}
        <rect width={W} height={H} fill="url(#bg-grid)" className="text-[var(--foreground)]" />

        {/* Pan/zoom group */}
        <g transform={`translate(${tf.x},${tf.y}) scale(${tf.s})`}>

          {/* ── Edges ── */}
          {edges.map((e, i) => {
            const a = pidx.get(e.a.toLowerCase()), b = pidx.get(e.b.toLowerCase());
            if (!a || !b) return null;
            const hi = connSet
              ? connSet.has(a.name.toLowerCase()) && connSet.has(b.name.toLowerCase())
              : false;
            // An edge is dim if either selection/hover or the source filter
            // says one of its endpoints is out.
            const filterDimA = filteringBySource && !nodeInFilter(a);
            const filterDimB = filteringBySource && !nodeInFilter(b);
            const dim = (!!connSet && !hi) || filterDimA || filterDimB;

            if (hasExplicitRels) {
              const { d, lx, ly } = edgePath(a.x, a.y, b.x, b.y, a.r, b.r);
              return (
                <g key={i}>
                  <path
                    d={d} fill="none"
                    stroke={dim ? "currentColor" : hi ? "white" : "var(--accent)"}
                    strokeOpacity={dim ? 0.04 : hi ? 0.95 : 0.35}
                    strokeWidth={hi ? 2.5 : 1.5}
                    markerEnd={dim ? "url(#arr-dim)" : hi ? "url(#arr-hi)" : "url(#arr)"}
                    className={dim ? "text-[var(--muted-foreground)]" : ""}
                  />
                  {hi && e.label && (
                    <>
                      <rect
                        x={lx - (e.label.length * 3.6 + 6)} y={ly - 11}
                        width={e.label.length * 7.2 + 12} height={17} rx={5}
                        fill="var(--accent)" fillOpacity={0.18}
                      />
                      <text x={lx} y={ly + 2} textAnchor="middle"
                        fontSize={10} fontWeight="700" fill="var(--accent)"
                        className="select-none pointer-events-none">
                        {e.label}
                      </text>
                    </>
                  )}
                  {!hi && !dim && e.label && (
                    <text x={lx} y={ly - 4} textAnchor="middle" fontSize={9}
                      fill="var(--muted-foreground)" fillOpacity={0.5}
                      className="select-none pointer-events-none">
                      {e.label}
                    </text>
                  )}
                </g>
              );
            }

            // undirected co-mention
            return (
              <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={dim ? "currentColor" : hi ? "white" : "var(--muted-foreground)"}
                strokeOpacity={dim ? 0.04 : hi ? 0.7 : 0.18}
                strokeWidth={hi ? 2.5 : 1}
                className={dim ? "text-[var(--muted-foreground)]" : ""}
              />
            );
          })}

          {/* ── Nodes ── */}
          {pnodes.map(p => {
            const isSel = selected?.toLowerCase() === p.name.toLowerCase();
            const isHov = hovered?.toLowerCase() === p.name.toLowerCase();
            const inFilter = nodeInFilter(p);
            const dim =
              (!!connSet && !connSet.has(p.name.toLowerCase())) ||
              (filteringBySource && !inFilter);
            // Highlight a node when it's the active source-filter match and
            // there's nothing else selected/hovered to compete with it.
            const filterHi = filteringBySource && inFilter && !connSet;
            const hi = isSel || isHov || filterHi;

            return (
              <g
                key={p.name}
                transform={`translate(${p.x},${p.y})`}
                style={{ cursor: "pointer", opacity: dim ? 0.13 : 1, transition: "opacity 0.15s" }}
                filter={hi ? "url(#glow-lg)" : undefined}
                onMouseEnter={() => setHovered(p.name)}
                onMouseLeave={() => setHovered(null)}
                onClick={ev => {
                  ev.stopPropagation();
                  setSelected(s => s === p.name ? null : p.name);
                }}
              >
                {/* Selection dashed ring */}
                {isSel && (
                  <circle r={p.r + 10} fill="none"
                    stroke={p.color} strokeWidth={1.5}
                    strokeOpacity={0.6} strokeDasharray="5 3" />
                )}
                {/* Glow halo */}
                {hi && <circle r={p.r + 6} fill={p.color} fillOpacity={0.2} />}
                {/* Main circle */}
                <circle r={p.r} fill={p.color}
                  fillOpacity={hi ? 1 : 0.85}
                  stroke="rgba(255,255,255,0.28)"
                  strokeWidth={hi ? 2.5 : 1.5}
                />
                {/* Inner shine */}
                <circle
                  cx={-p.r * 0.28} cy={-p.r * 0.32}
                  r={p.r * 0.38}
                  fill="white" fillOpacity={0.13}
                />
                {/* Label — stroke trick for readability without a bg rect */}
                <text
                  y={p.r + 15} textAnchor="middle"
                  fontSize={hi ? 12 : 11}
                  fontWeight={hi ? "600" : "400"}
                  fill="var(--foreground)"
                  stroke="var(--background)"
                  strokeWidth={3}
                  paintOrder="stroke"
                  className="select-none pointer-events-none"
                >
                  {p.name}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* ── Controls (top-right) ── */}
      <div className="absolute top-3 right-3 z-10 flex flex-col gap-1">
        <button title="Zoom in" onClick={() => setTf(t => ({ ...t, s: Math.min(7, t.s * 1.3) }))}
          className="size-8 rounded border border-[var(--border)] bg-[var(--background)]/90 backdrop-blur-sm text-sm font-mono hover:bg-[var(--muted)] transition-colors flex items-center justify-center shadow-sm">
          +
        </button>
        <button title="Zoom out" onClick={() => setTf(t => ({ ...t, s: Math.max(0.12, t.s / 1.3) }))}
          className="size-8 rounded border border-[var(--border)] bg-[var(--background)]/90 backdrop-blur-sm text-sm font-mono hover:bg-[var(--muted)] transition-colors flex items-center justify-center shadow-sm">
          −
        </button>
        <button title="Fit to screen" onClick={fitScreen}
          className="size-8 rounded border border-[var(--border)] bg-[var(--background)]/90 backdrop-blur-sm text-sm font-mono hover:bg-[var(--muted)] transition-colors flex items-center justify-center shadow-sm">
          ⊡
        </button>
        <button title={isFull ? "Exit fullscreen" : "Fullscreen"} onClick={toggleFull}
          className="size-8 rounded border border-[var(--border)] bg-[var(--background)]/90 backdrop-blur-sm text-sm font-mono hover:bg-[var(--muted)] transition-colors flex items-center justify-center shadow-sm">
          {isFull ? "⊠" : "⤢"}
        </button>
      </div>

      {/* ── Legend (top-left) ── */}
      <div className="absolute top-3 left-3 z-10 rounded-lg border border-[var(--border)] bg-[var(--background)]/90 backdrop-blur-sm px-3 py-2.5 text-[11px] min-w-[180px]">
        <div className="text-[10px] font-semibold uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
          {hasExplicitRels ? "Knowledge graph" : "Co-mention graph"}
        </div>
        <div className="space-y-1">
          {presentKinds.map(k => (
            <div key={k} className="flex items-center gap-1.5">
              <span className="size-2 rounded-full flex-shrink-0" style={{ background: KIND_COLOR[k] }} />
              <span className="text-[var(--muted-foreground)]">{KIND_LABEL[k] ?? k}</span>
              <span className="ml-auto font-mono font-medium tabular-nums">
                {nodes.filter(n => n.kind === k).length}
              </span>
            </div>
          ))}
        </div>

        {/* Source-type filter — highlights nodes drawn from docs or slack. */}
        <SourceFilter
          nodes={nodes}
          active={sourceFilter}
          onToggle={toggleSourceFilter}
        />

        {hasExplicitRels && (
          <div className="mt-2 pt-2 border-t border-[var(--border)] flex items-center gap-1 text-[var(--muted-foreground)]">
            <span className="text-[var(--accent)] font-bold">→</span>
            <span>directed edge</span>
          </div>
        )}
        <div className="mt-2 pt-2 border-t border-[var(--border)] text-[var(--muted-foreground)]">
          Scroll to zoom · drag to pan
          <br />Click a node to inspect
        </div>
      </div>

      {/* ── Node info panel (bottom-left, appears on click) ── */}
      {selNode && (
        <div className="absolute bottom-3 left-3 z-10 rounded-lg border border-[var(--border)] bg-[var(--background)]/95 backdrop-blur-sm px-4 py-3 min-w-[220px] max-w-[360px] shadow-lg">
          <div className="flex items-start justify-between gap-3 mb-2.5">
            <div className="flex items-center gap-2">
              <span
                className="size-3.5 rounded-full flex-shrink-0 shadow-sm"
                style={{ background: selNode.color, boxShadow: `0 0 8px ${selNode.color}88` }}
              />
              <div>
                <div className="font-semibold text-sm leading-tight">{selNode.name}</div>
                <div className="text-[10px] text-[var(--muted-foreground)] uppercase tracking-widest mt-0.5">
                  {selNode.kind}
                </div>
              </div>
            </div>
            <button
              onClick={() => setSelected(null)}
              className="text-[var(--muted-foreground)] hover:text-[var(--foreground)] text-xs leading-none mt-0.5 transition-colors"
            >
              ✕
            </button>
          </div>

          {selConns.length > 0 ? (
            <div className="space-y-1.5 max-h-40 overflow-y-auto">
              {selConns.map((e, i) => (
                <div key={i} className="flex items-center gap-1 text-[11px] flex-wrap leading-snug">
                  <span className="font-medium">{e.a}</span>
                  <span className="font-mono text-[var(--accent)] text-[10px] px-1">
                    →{e.label ?? "—"}→
                  </span>
                  <span className="font-medium">{e.b}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[11px] text-[var(--muted-foreground)]">
              No relationships indexed yet.
            </p>
          )}

          {selConns.length > 0 && (
            <div className="mt-2 pt-2 border-t border-[var(--border)] text-[10px] text-[var(--muted-foreground)]">
              {selConns.length} direct relationship{selConns.length !== 1 ? "s" : ""}
              {" · "}
              {nodes.find(n => n.name === selNode.name)?.refCount ?? 0} knowledge unit{(nodes.find(n => n.name === selNode.name)?.refCount ?? 0) !== 1 ? "s" : ""}
            </div>
          )}
        </div>
      )}

      {/* ── Empty hint ── */}
      {pnodes.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-[var(--muted-foreground)] text-sm pointer-events-none">
          No entities yet — ingest content to build the map.
        </div>
      )}
    </div>
  );
}

// ── Source-type filter chips ───────────────────────────────────────────────────

const SOURCE_TAGS: { tag: SourceTag; label: string; swatch: string }[] = [
  { tag: "doc", label: "Docs", swatch: "#60a5fa" },
  { tag: "slack", label: "Slack", swatch: "#a78bfa" },
];

function SourceFilter({
  nodes,
  active,
  onToggle,
}: {
  nodes: Node[];
  active: Set<SourceTag>;
  onToggle: (t: SourceTag) => void;
}) {
  // Per-tag counts so the user sees how many entities each filter will match.
  const counts = useMemo(() => {
    const out: Record<SourceTag, number> = { doc: 0, slack: 0 };
    for (const n of nodes) {
      for (const t of n.sources ?? []) {
        if (t in out) out[t] += 1;
      }
    }
    return out;
  }, [nodes]);

  const anyTagged = counts.doc + counts.slack > 0;
  if (!anyTagged) return null;

  return (
    <div className="mt-2 pt-2 border-t border-[var(--border)]">
      <div className="text-[10px] font-semibold uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
        Filter by source
      </div>
      <div className="flex flex-wrap gap-1.5">
        {SOURCE_TAGS.map(({ tag, label, swatch }) => {
          const isActive = active.has(tag);
          return (
            <button
              key={tag}
              type="button"
              onClick={() => onToggle(tag)}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                isActive
                  ? "border-[var(--accent)] bg-[var(--accent)]/15 text-[var(--foreground)]"
                  : "border-[var(--border)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
              aria-pressed={isActive}
            >
              <span
                className="size-1.5 rounded-full"
                style={{ background: swatch }}
                aria-hidden
              />
              {label}
              <span className="font-mono tabular-nums opacity-70">{counts[tag]}</span>
            </button>
          );
        })}
      </div>
      <p className="mt-1.5 text-[10px] leading-tight text-[var(--muted-foreground)]">
        {active.size === 0
          ? "Click a tag to highlight its entities"
          : active.size === 2
            ? "Showing all"
            : `Highlighting ${active.size === 1 ? "one" : "both"} source${active.size === 1 ? "" : "s"}`}
      </p>
    </div>
  );
}
