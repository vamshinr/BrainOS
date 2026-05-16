"use client";

import { useEffect, useState, useCallback } from "react";

// ── Types ──────────────────────────────────────────────────────────────────────
type GpuMetrics = {
  backend: string;
  model: string;
  vllm_endpoint: string;
  vllm_metrics_url?: string;
  serving_config?: {
    model: string;
    dtype: string;
    max_model_len: number | null;
    gpu_memory_utilization: number | null;
    max_num_batched_tokens: number | null;
    max_num_seqs: number | null;
    chunked_prefill: boolean;
    prefix_caching: boolean;
    auto_tool_choice: boolean;
    tool_call_parser: string;
  };
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

type Route = {
  task: string;
  model: string;
  endpoint: string;
  shared_with_default: boolean;
};

type RecentCall = {
  ts: string;
  task: string;
  model: string;
  latency_ms: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  ok: boolean;
  note: string;
};

type Snapshot = {
  gpu: GpuMetrics;
  rag: RagMetrics;
  knowledge: KnowledgeMetrics;
  vlm: VlmInfo;
  routes: Route[];
  recent_calls: RecentCall[];
  ts: number; // client timestamp
};

const REFRESH_MS = 5000;

const TASK_TINT: Record<string, string> = {
  extraction: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  reconcile: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  execute: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  feedback: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
  vlm: "bg-pink-100 text-pink-800 dark:bg-pink-900/40 dark:text-pink-300",
};

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

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-[var(--muted)]/20 px-3 py-2">
      <div className="text-[9px] uppercase tracking-widest text-[var(--muted-foreground)]">
        {label}
      </div>
      <div className="mt-1 font-mono text-sm font-semibold">{value}</div>
    </div>
  );
}

function KvCachePanel({ gpu }: { gpu: GpuMetrics }) {
  const gpuPct = gpu.gpu_cache_usage_pct !== null ? gpu.gpu_cache_usage_pct * 100 : null;
  const cpuPct = gpu.cpu_cache_usage_pct !== null ? gpu.cpu_cache_usage_pct * 100 : null;
  const configuredGpu = gpu.serving_config?.gpu_memory_utilization;

  return (
    <div className="rounded-lg border bg-[var(--card)] px-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
            KV cache pressure
          </div>
          <div className="mt-1 text-sm text-[var(--muted-foreground)]">
            vLLM cache occupancy from the Gemma serving process.
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-2xl font-semibold text-[var(--accent)]">
            {gpuPct !== null ? `${gpuPct.toFixed(1)}%` : "—"}
          </div>
          <div className="text-[10px] text-[var(--muted-foreground)]">GPU KV</div>
        </div>
      </div>

      <div className="mt-4 space-y-4">
        <CacheBar label="GPU KV-cache live usage" pct={gpuPct} />
        <CacheBar label="CPU KV-cache spillover" pct={cpuPct} />
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2">
        <MetricPill
          label="GPU mem target"
          value={configuredGpu !== null && configuredGpu !== undefined ? `${(configuredGpu * 100).toFixed(0)}%` : "—"}
        />
        <MetricPill
          label="Max sequences"
          value={gpu.serving_config?.max_num_seqs ? String(gpu.serving_config.max_num_seqs) : "—"}
        />
        <MetricPill
          label="Context"
          value={gpu.serving_config?.max_model_len ? `${Math.round(gpu.serving_config.max_model_len / 1024)}K` : "—"}
        />
        <MetricPill
          label="Batch tokens"
          value={gpu.serving_config?.max_num_batched_tokens ? String(gpu.serving_config.max_num_batched_tokens) : "—"}
        />
      </div>

      {!gpu.prometheus_reachable && (
        <div className="mt-4 rounded-md border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-[11px] leading-relaxed text-amber-700 dark:text-amber-300">
          KV cache is unavailable because Prometheus metrics are not reachable.
          Set <code className="font-mono">VLLM_METRICS_BASE</code> or{" "}
          <code className="font-mono">AGENT_API_BASE</code> to the Gemma vLLM base URL, for example{" "}
          <code className="font-mono">http://165.245.128.5:8001/v1</code>.
        </div>
      )}
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
  const [, setTick] = useState(0); // for relative-time re-render
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
    const immediate = setTimeout(fetchMetrics, 0);
    const id = setInterval(fetchMetrics, REFRESH_MS);
    return () => {
      clearTimeout(immediate);
      clearInterval(id);
    };
  }, [fetchMetrics]);

  // Tick every second so relative time updates
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="px-4 sm:px-6 md:px-10 py-6 md:py-10 max-w-5xl">
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
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 mb-4">
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
                label="Total LLM calls"
                value={String(Math.round(snapshot.gpu.total_requests_finished))}
                sub="finished on this vLLM since startup"
              />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] gap-4">
              {/* Throughput sparkline */}
              <div className="rounded-lg border bg-[var(--card)] px-4 py-3">
                <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
                  Generation throughput (tok/s) — last {genHistory.length} samples
                </div>
                <Sparkline values={genHistory} height={56} />

                <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <MetricPill
                    label="DType"
                    value={snapshot.gpu.serving_config?.dtype ?? "—"}
                  />
                  <MetricPill
                    label="Chunked prefill"
                    value={snapshot.gpu.serving_config?.chunked_prefill ? "on" : "off"}
                  />
                  <MetricPill
                    label="Prefix cache"
                    value={snapshot.gpu.serving_config?.prefix_caching ? "on" : "off"}
                  />
                  <MetricPill
                    label="Tool parser"
                    value={snapshot.gpu.serving_config?.tool_call_parser ?? "—"}
                  />
                </div>
              </div>

              {/* Queue + cache */}
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <StatCard
                    label="Running"
                    value={String(Math.round(snapshot.gpu.requests_running))}
                    sub="active requests"
                    accent={snapshot.gpu.requests_running > 0}
                  />
                  <StatCard
                    label="Waiting"
                    value={String(Math.round(snapshot.gpu.requests_waiting))}
                    sub="queued requests"
                    warn={snapshot.gpu.requests_waiting > 0}
                  />
                </div>
                <KvCachePanel gpu={snapshot.gpu} />
              </div>
            </div>

            {/* Model info strip */}
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[var(--muted-foreground)]">
              <span>Serving: <span className="font-mono text-[var(--foreground)]">{snapshot.gpu.serving_config?.model ?? snapshot.gpu.model}</span></span>
              <span>·</span>
              <span>Endpoint: <span className="font-mono">{snapshot.gpu.vllm_endpoint}</span></span>
              {snapshot.gpu.vllm_metrics_url && (
                <>
                  <span>·</span>
                  <span>Metrics: <span className="font-mono">{snapshot.gpu.vllm_metrics_url}</span></span>
                </>
              )}
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
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
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
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
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

          {/* ── Model routing ── */}
          <section>
            <SectionTitle>Model routing — which model handles what</SectionTitle>
            <div className="rounded-lg border bg-[var(--card)] overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-[var(--muted)]/30 text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
                    <th className="text-left px-4 py-2.5">Task</th>
                    <th className="text-left px-4 py-2.5">Model</th>
                    <th className="text-left px-4 py-2.5">Endpoint</th>
                    <th className="text-right px-4 py-2.5">Mode</th>
                  </tr>
                </thead>
                <tbody>
                  {(snapshot.routes ?? []).map((r) => (
                    <tr key={r.task} className="border-b last:border-0">
                      <td className="px-4 py-2 font-mono text-[12px]">{r.task}</td>
                      <td className="px-4 py-2 font-mono text-[11px]">{r.model}</td>
                      <td className="px-4 py-2 font-mono text-[10px] text-[var(--muted-foreground)] truncate max-w-[260px]">
                        {r.endpoint}
                      </td>
                      <td className="px-4 py-2 text-right">
                        {r.shared_with_default ? (
                          <span className="text-[10px] rounded bg-[var(--muted)]/40 text-[var(--muted-foreground)] px-1.5 py-0.5">
                            shared
                          </span>
                        ) : (
                          <span className="text-[10px] rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300 px-1.5 py-0.5">
                            custom
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-2 text-[11px] text-[var(--muted-foreground)]">
              Override via env vars: <code className="font-mono">EXTRACTION_MODEL</code>,{" "}
              <code className="font-mono">EXTRACTION_API_BASE</code>,{" "}
              <code className="font-mono">RECONCILE_MODEL</code>, etc. Restart the Python
              backend after changing.
            </p>
          </section>

          {/* ── Live LLM call log ── */}
          <section>
            <SectionTitle>
              Recent LLM calls — live ({(snapshot.recent_calls ?? []).length})
            </SectionTitle>
            {(snapshot.recent_calls ?? []).length === 0 ? (
              <div className="rounded-lg border border-dashed bg-[var(--muted)]/30 px-4 py-6 text-sm text-center text-[var(--muted-foreground)]">
                No LLM calls yet. Ingest something or ask a question to populate.
              </div>
            ) : (
              <div className="rounded-lg border bg-[var(--card)] overflow-hidden">
                <table className="w-full text-[12px]">
                  <thead>
                    <tr className="border-b bg-[var(--muted)]/30 text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
                      <th className="text-left px-3 py-2">Time</th>
                      <th className="text-left px-3 py-2">Task</th>
                      <th className="text-left px-3 py-2">Model</th>
                      <th className="text-right px-3 py-2">Latency</th>
                      <th className="text-right px-3 py-2">Prompt tok</th>
                      <th className="text-right px-3 py-2">Out tok</th>
                      <th className="text-left px-3 py-2">Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(snapshot.recent_calls ?? [])
                      .slice()
                      .reverse()
                      .slice(0, 25)
                      .map((c, i) => (
                        <tr
                          key={`${c.ts}-${i}`}
                          className={`border-b last:border-0 ${!c.ok ? "bg-red-50 dark:bg-red-950/20" : ""}`}
                        >
                          <td className="px-3 py-1.5 text-[10px] font-mono text-[var(--muted-foreground)] whitespace-nowrap">
                            {new Date(c.ts).toLocaleTimeString()}
                          </td>
                          <td className="px-3 py-1.5">
                            <span
                              className={`text-[10px] font-mono rounded px-1.5 py-0.5 ${TASK_TINT[c.task] ?? "bg-[var(--muted)]/40"}`}
                            >
                              {c.task}
                            </span>
                          </td>
                          <td className="px-3 py-1.5 font-mono text-[10px] text-[var(--muted-foreground)] truncate max-w-[180px]">
                            {c.model}
                          </td>
                          <td className="px-3 py-1.5 text-right font-mono">{c.latency_ms} ms</td>
                          <td className="px-3 py-1.5 text-right font-mono text-[var(--muted-foreground)]">
                            {c.prompt_tokens ?? "—"}
                          </td>
                          <td className="px-3 py-1.5 text-right font-mono text-[var(--muted-foreground)]">
                            {c.completion_tokens ?? "—"}
                          </td>
                          <td className="px-3 py-1.5 text-[10px] text-[var(--muted-foreground)] truncate max-w-[260px]">
                            {c.ok ? c.note : `❌ ${c.note}`}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="mt-2 text-[11px] text-[var(--muted-foreground)]">
              In-process log — last 80 calls across extraction, reconcile, execute, feedback,
              and VLM. Refreshes every {REFRESH_MS / 1000}s. Resets when the Python backend restarts.
            </p>
          </section>

          {/* ── AMD pitch callout ── */}
          <section>
            <div className="rounded-lg border border-[var(--accent)]/30 bg-[var(--accent)]/5 px-5 py-4 text-sm">
              <div className="font-semibold mb-1">Why AMD MI300X?</div>
              <p className="text-[var(--muted-foreground)] text-[13px] leading-relaxed">
                192 GB of unified HBM3 memory lets BrainOS run a 70B text model{" "}
                <em>and</em> a vision model simultaneously on a single GPU — no multi-node
                orchestration, no model-splitting overhead. On an NVIDIA H100 (80 GB)
                this requires 3+ GPUs. Here it is one card.
              </p>
            </div>
          </section>

        </div>
      )}
    </div>
  );
}
