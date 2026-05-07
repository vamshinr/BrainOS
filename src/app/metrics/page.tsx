"use client";

import { useEffect, useState, useCallback } from "react";

// ── Types ──────────────────────────────────────────────────────────────────────
type GpuMetrics = {
  backend: string;
  model: string;
  vllm_endpoint: string;
  tokens_per_sec_generation: number | null;
  tokens_per_sec_prompt: number | null;
  requests_running: number;
  requests_waiting: number;
  gpu_cache_usage_pct: number | null;
  cpu_cache_usage_pct: number | null;
  avg_e2e_latency_s: number | null;
  total_requests_finished: number;
  prometheus_reachable: boolean;
};

type RagMetrics = {
  embedding_backend: string;
  embedding_model: string;
  chroma_units: number;
};

type KnowledgeMetrics = {
  sources: number;
  entities: number;
  units: number;
  stale_units: number;
};

type VlmInfo = {
  model: string;
  endpoint: string;
};

type Snapshot = {
  gpu: GpuMetrics;
  rag: RagMetrics;
  knowledge: KnowledgeMetrics;
  vlm: VlmInfo;
  ts: number; // client timestamp
};

const REFRESH_MS = 5000;

// ── Helpers ────────────────────────────────────────────────────────────────────
function fmt(n: number | null | undefined, decimals = 1, unit = ""): string {
  if (n === null || n === undefined) return "—";
  return `${n.toFixed(decimals)}${unit}`;
}

function relativeTime(ts: number): string {
  const s = Math.round((Date.now() - ts) / 1000);
  if (s < 2) return "just now";
  return `${s}s ago`;
}

// ── Sub-components ─────────────────────────────────────────────────────────────
function StatCard({
  label,
  value,
  sub,
  accent,
  warn,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
  warn?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border bg-[var(--card)] px-4 py-3 ${
        warn ? "border-amber-400/50" : ""
      }`}
    >
      <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
        {label}
      </div>
      <div
        className={`mt-1 text-2xl font-semibold tabular-nums font-mono ${
          accent
            ? "text-[var(--accent)]"
            : warn
            ? "text-amber-500"
            : ""
        }`}
      >
        {value}
      </div>
      {sub && (
        <div className="mt-0.5 text-[11px] text-[var(--muted-foreground)] truncate">
          {sub}
        </div>
      )}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
      {children}
    </h2>
  );
}

function CacheBar({ label, pct }: { label: string; pct: number | null }) {
  const val = pct ?? 0;
  const color =
    val > 90 ? "bg-red-500" : val > 70 ? "bg-amber-400" : "bg-emerald-500";
  return (
    <div>
      <div className="flex justify-between text-[11px] mb-1">
        <span className="text-[var(--muted-foreground)]">{label}</span>
        <span className="font-mono">{pct !== null ? `${val.toFixed(1)}%` : "—"}</span>
      </div>
      <div className="h-2 rounded-full bg-[var(--muted)]/40 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${color}`}
          style={{ width: `${Math.min(val, 100)}%` }}
        />
      </div>
    </div>
  );
}

// ── Throughput sparkline (last N readings) ─────────────────────────────────────
function Sparkline({ values, height = 40 }: { values: number[]; height?: number }) {
  if (values.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-[11px] text-[var(--muted-foreground)] border rounded-md bg-[var(--muted)]/20"
        style={{ height }}
      >
        Collecting data…
      </div>
    );
  }
  const max = Math.max(...values, 1);
  const W = 300;
  const H = height;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * W;
    const y = H - (v / max) * H * 0.9 - 2;
    return `${x},${y}`;
  });
  const path = `M${pts.join("L")}`;
  const fill = `M0,${H} L${pts.join("L")} L${W},${H} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }}>
      <path d={fill} fill="currentColor" className="text-[var(--accent)]/10" />
      <path d={path} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-[var(--accent)]" />
    </svg>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function MetricsPage() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<number | null>(null);
  const [tick, setTick] = useState(0); // for relative-time re-render
  // Rolling throughput history for sparkline (max 30 points)
  const [genHistory, setGenHistory] = useState<number[]>([]);

  const fetchMetrics = useCallback(async () => {
    try {
      const res = await fetch("/api/metrics", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      const snap: Snapshot = { ...data, ts: Date.now() };
      setSnapshot(snap);
      setLastUpdate(Date.now());
      setError(null);
      if (snap.gpu.tokens_per_sec_generation !== null) {
        setGenHistory((h) => [...h.slice(-29), snap.gpu.tokens_per_sec_generation!]);
      }
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    }
  }, []);

  useEffect(() => {
    fetchMetrics();
    const id = setInterval(fetchMetrics, REFRESH_MS);
    return () => clearInterval(id);
  }, [fetchMetrics]);

  // Tick every second so relative time updates
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="px-10 py-10 max-w-5xl">
      {/* Header */}
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        GPU Metrics
      </div>
      <div className="flex items-end justify-between">
        <h1 className="text-3xl font-semibold tracking-tight">
          AMD MI300X live dashboard.
        </h1>
        <div className="flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
          <span
            className={`size-2 rounded-full inline-block ${
              snapshot
                ? snapshot.gpu.prometheus_reachable
                  ? "bg-emerald-500 animate-pulse"
                  : "bg-amber-400"
                : "bg-zinc-400"
            }`}
          />
          {snapshot
            ? snapshot.gpu.prometheus_reachable
              ? "Live (Prometheus)"
              : "Connected · Prometheus unreachable"
            : "Connecting…"}
          {lastUpdate && (
            <span className="ml-2">· Updated {relativeTime(lastUpdate)}</span>
          )}
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {error} — is the Python backend running on :8081?
        </div>
      )}

      {!snapshot && !error && (
        <div className="mt-10 text-sm text-[var(--muted-foreground)]">Loading…</div>
      )}

      {snapshot && (
        <div className="mt-8 space-y-10">

          {/* ── GPU / vLLM ── */}
          <section>
            <SectionTitle>GPU · vLLM · {snapshot.gpu.backend}</SectionTitle>
            <div className="grid grid-cols-4 gap-3 mb-4">
              <StatCard
                label="Generation tok/s"
                value={fmt(snapshot.gpu.tokens_per_sec_generation, 1)}
                sub="avg since startup"
                accent
              />
              <StatCard
                label="Prompt tok/s"
                value={fmt(snapshot.gpu.tokens_per_sec_prompt, 1)}
                sub="avg since startup"
              />
              <StatCard
                label="Avg E2E latency"
                value={
                  snapshot.gpu.avg_e2e_latency_s !== null
                    ? `${(snapshot.gpu.avg_e2e_latency_s * 1000).toFixed(0)} ms`
                    : "—"
                }
                sub="end-to-end per request"
              />
              <StatCard
                label="Total requests"
                value={String(Math.round(snapshot.gpu.total_requests_finished))}
                sub="finished"
              />
            </div>

            <div className="grid grid-cols-[1fr_220px] gap-4">
              {/* Throughput sparkline */}
              <div className="rounded-lg border bg-[var(--card)] px-4 py-3">
                <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
                  Generation throughput (tok/s) — last {genHistory.length} samples
                </div>
                <Sparkline values={genHistory} height={56} />
              </div>

              {/* Queue + cache */}
              <div className="rounded-lg border bg-[var(--card)] px-4 py-3 space-y-4">
                <div className="flex gap-4">
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">Running</div>
                    <div className="mt-1 text-xl font-semibold font-mono">
                      {Math.round(snapshot.gpu.requests_running)}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">Waiting</div>
                    <div
                      className={`mt-1 text-xl font-semibold font-mono ${
                        snapshot.gpu.requests_waiting > 0 ? "text-amber-500" : ""
                      }`}
                    >
                      {Math.round(snapshot.gpu.requests_waiting)}
                    </div>
                  </div>
                </div>
                <CacheBar label="GPU KV-cache" pct={snapshot.gpu.gpu_cache_usage_pct !== null ? snapshot.gpu.gpu_cache_usage_pct * 100 : null} />
                <CacheBar label="CPU KV-cache" pct={snapshot.gpu.cpu_cache_usage_pct !== null ? snapshot.gpu.cpu_cache_usage_pct * 100 : null} />
              </div>
            </div>

            {/* Model info strip */}
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--muted-foreground)]">
              <span>Model: <span className="font-mono text-[var(--foreground)]">{snapshot.gpu.model}</span></span>
              <span>·</span>
              <span>Endpoint: <span className="font-mono">{snapshot.gpu.vllm_endpoint}</span></span>
              {!snapshot.gpu.prometheus_reachable && (
                <>
                  <span>·</span>
                  <span className="text-amber-500">
                    Prometheus unreachable — live tok/s and latency unavailable.
                    vLLM exposes /metrics at its base URL.
                  </span>
                </>
              )}
            </div>
          </section>

          {/* ── RAG / ChromaDB ── */}
          <section>
            <SectionTitle>RAG · ChromaDB</SectionTitle>
            <div className="grid grid-cols-3 gap-3">
              <StatCard
                label="Embedded units"
                value={String(snapshot.rag.chroma_units)}
                sub="in ChromaDB vector store"
                accent
              />
              <StatCard
                label="Knowledge sources"
                value={String(snapshot.knowledge.sources)}
                sub="ingested documents"
              />
              <StatCard
                label="Stale / superseded"
                value={String(snapshot.knowledge.stale_units)}
                sub="reconciled out of date"
                warn={snapshot.knowledge.stale_units > 0}
              />
            </div>
            <div className="mt-3 text-[11px] text-[var(--muted-foreground)]">
              Embedding:{" "}
              <span className={`font-mono ${snapshot.rag.embedding_backend.startsWith("GPU") ? "text-emerald-600 dark:text-emerald-400" : ""}`}>
                {snapshot.rag.embedding_backend}
              </span>
              {" · "}
              {snapshot.knowledge.entities} entities ·{" "}
              {snapshot.knowledge.units} knowledge units in brain.json
            </div>
          </section>

          {/* ── VLM ── */}
          <section>
            <SectionTitle>VLM · Vision Language Model</SectionTitle>
            <div className="rounded-lg border bg-[var(--card)] px-4 py-3">
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">
                    Model
                  </div>
                  <div className="font-mono text-sm">{snapshot.vlm.model}</div>
                </div>
                <div>
                  <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">
                    Endpoint
                  </div>
                  <div className="font-mono text-sm">{snapshot.vlm.endpoint}</div>
                </div>
              </div>
              <div className="mt-3 text-[11px] text-[var(--muted-foreground)]">
                Set <code className="font-mono">VLM_API_BASE</code> and{" "}
                <code className="font-mono">VLM_MODEL_NAME</code> in{" "}
                <code className="font-mono">src/python_backend/.env</code> to
                activate image ingestion on the AMD MI300X.
              </div>
            </div>
          </section>

          {/* ── AMD pitch callout ── */}
          <section>
            <div className="rounded-lg border border-[var(--accent)]/30 bg-[var(--accent)]/5 px-5 py-4 text-sm">
              <div className="font-semibold mb-1">Why AMD MI300X?</div>
              <p className="text-[var(--muted-foreground)] text-[13px] leading-relaxed">
                192 GB of unified HBM3 memory lets BrainOS run a 70B text model{" "}
                <em>and</em> a vision model simultaneously on a single GPU — no multi-node
                orchestration, no model-splitting overhead. On an NVIDIA H100 (80 GB)
                this requires 3+ GPUs. Here it's one card.
              </p>
            </div>
          </section>

        </div>
      )}
    </div>
  );
}
