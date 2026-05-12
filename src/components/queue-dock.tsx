"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";

type JobStatus = "queued" | "running" | "completed" | "failed" | "canceled";
type JobKind = "ingest_text" | "ingest_file" | "ingest_image" | string;

interface Job {
  id: string;
  kind: JobKind;
  title: string;
  status: JobStatus;
  progress: number; // 0..1
  step: string | null;
  error: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

interface Snapshot {
  active: Job | null;
  queued: Job[];
  recent: Job[];
}

const KIND_LABEL: Record<string, string> = {
  ingest_text: "text",
  ingest_file: "file",
  ingest_image: "image",
};

const STATUS_DOT: Record<JobStatus, string> = {
  queued: "bg-zinc-400",
  running: "bg-blue-500 animate-pulse",
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  canceled: "bg-zinc-500",
};

export function QueueDock() {
  const [snap, setSnap] = useState<Snapshot>({
    active: null,
    queued: [],
    recent: [],
  });
  const [open, setOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  const router = useRouter();
  const lastFinishedAt = useRef<string | null>(null);

  // Trigger a server-side cache invalidate + router refresh. Marked by the
  // job's finishedAt so the same finish never invalidates twice.
  const onJobFinished = useCallback((finishedAt: string | null) => {
    if (!finishedAt || finishedAt === lastFinishedAt.current) return;
    lastFinishedAt.current = finishedAt;
    fetch("/api/cache/invalidate", { method: "POST" })
      .catch(() => {})
      .finally(() => router.refresh());
  }, [router]);

  // Apply a single SSE event to the snapshot. Server sends snapshot resets
  // and per-job deltas; we mutate the local state accordingly.
  const applyEvent = useCallback((data: { event: string; snapshot?: Snapshot; job?: Job }) => {
    if (data.event === "snapshot" && data.snapshot) {
      setSnap(data.snapshot);
      // Defensive: if the stream reconnected after a disconnect, we may have
      // missed the live job.finished event. Invalidate using the most-recent
      // finished job from the snapshot — onJobFinished deduplicates by id.
      const newest = data.snapshot.recent.find((j) => j.status === "completed" || j.status === "failed");
      if (newest?.finishedAt) onJobFinished(newest.finishedAt);
      return;
    }
    if (!data.job) return;
    const job = data.job;
    setSnap((prev) => {
      const queued = prev.queued.filter((j) => j.id !== job.id);
      const recent = prev.recent.filter((j) => j.id !== job.id);
      let active = prev.active && prev.active.id === job.id ? job : prev.active;

      if (job.status === "queued") {
        queued.push(job);
      } else if (job.status === "running") {
        active = job;
      } else {
        // completed / failed / canceled
        recent.unshift(job);
        if (active && active.id === job.id) active = null;
      }
      return { active, queued, recent: recent.slice(0, 20) };
    });

    // When a job finishes, brain.json has new content but Next.js's
    // unstable_cache still serves the old snapshot. Bust it server-side, then
    // refresh the route so /, /graph, /skills, etc. re-render with fresh data.
    if (job.status === "completed" || job.status === "failed") {
      onJobFinished(job.finishedAt);
    }
  }, [onJobFinished]);

  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (cancelled) return;
      es = new EventSource("/api/jobs/stream");
      es.onopen = () => setConnected(true);
      es.onmessage = (ev) => {
        try {
          applyEvent(JSON.parse(ev.data));
        } catch {
          // ignore malformed frames (e.g. heartbeats)
        }
      };
      es.onerror = () => {
        setConnected(false);
        es?.close();
        if (!cancelled) retryTimer = setTimeout(connect, 3000);
      };
    };

    // Seed with snapshot in case SSE is slow to open.
    fetch("/api/jobs", { cache: "no-store" })
      .then((r) => r.json())
      .then((s) => !cancelled && setSnap(s))
      .catch(() => {});

    connect();
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
    };
  }, [applyEvent]);

  const { active, queued, recent } = snap;
  const idle = !active && queued.length === 0;

  // Cancel a queued (not yet running) job
  const cancel = async (id: string) => {
    try {
      await fetch(`/api/jobs/${id}`, { method: "DELETE" });
    } catch {}
  };

  return (
    <div className="fixed bottom-4 right-4 z-50 w-[320px]">
      <div className="rounded-lg border bg-[var(--card)] shadow-lg overflow-hidden">
        {/* Header — clickable to toggle */}
        <button
          onClick={() => setOpen((o) => !o)}
          className="w-full flex items-center gap-2.5 px-3.5 py-2.5 hover:bg-[var(--muted)]/40 transition-colors text-left"
        >
          <span
            className={`size-2 rounded-full shrink-0 ${
              active ? STATUS_DOT.running : connected ? "bg-emerald-500" : "bg-zinc-400"
            }`}
            title={connected ? "live" : "disconnected"}
          />
          <div className="flex-1 min-w-0">
            {active ? (
              <>
                <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
                  Processing · {KIND_LABEL[active.kind] ?? active.kind}
                </div>
                <div className="text-sm font-medium truncate">{active.title}</div>
              </>
            ) : queued.length > 0 ? (
              <>
                <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
                  Queued
                </div>
                <div className="text-sm font-medium truncate">
                  {queued.length} waiting
                </div>
              </>
            ) : (
              <>
                <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
                  Queue
                </div>
                <div className="text-sm font-medium truncate text-[var(--muted-foreground)]">
                  Idle
                </div>
              </>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {queued.length > 0 && (
              <span className="text-[11px] font-mono text-[var(--muted-foreground)]">
                +{queued.length}
              </span>
            )}
            <span
              className={`text-[var(--muted-foreground)] transition-transform ${
                open ? "rotate-180" : ""
              }`}
            >
              ⌃
            </span>
          </div>
        </button>

        {/* Active progress bar — always visible when something is running */}
        {active && (
          <div className="px-3.5 pb-2">
            <div className="h-1 rounded-full bg-[var(--muted)] overflow-hidden">
              <div
                className="h-full bg-[var(--accent)] transition-all"
                style={{ width: `${Math.max(4, Math.round(active.progress * 100))}%` }}
              />
            </div>
            {active.step && (
              <div className="mt-1.5 text-[11px] text-[var(--muted-foreground)] truncate">
                {active.step}
              </div>
            )}
          </div>
        )}

        {/* Expanded panel — queued + recent */}
        {open && (
          <div className="border-t bg-[var(--background)]/60 max-h-[60vh] overflow-y-auto">
            {!idle && queued.length > 0 && (
              <div className="px-3.5 py-2.5">
                <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
                  Queued
                </div>
                <ul className="space-y-1">
                  {queued.map((j, i) => (
                    <li
                      key={j.id}
                      className="flex items-center gap-2 text-xs group"
                    >
                      <span className="font-mono text-[10px] text-[var(--muted-foreground)] w-4 text-right">
                        {i + 1}
                      </span>
                      <span className="size-1.5 rounded-full bg-zinc-400 shrink-0" />
                      <span className="flex-1 truncate">{j.title}</span>
                      <span className="text-[10px] text-[var(--muted-foreground)] uppercase tracking-wide">
                        {KIND_LABEL[j.kind] ?? j.kind}
                      </span>
                      <button
                        onClick={() => cancel(j.id)}
                        className="opacity-0 group-hover:opacity-100 text-[10px] text-red-500 hover:underline transition-opacity"
                        aria-label="cancel"
                        title="Cancel"
                      >
                        ✕
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {recent.length > 0 && (
              <div className="px-3.5 py-2.5 border-t">
                <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
                  Recent
                </div>
                <ul className="space-y-1">
                  {recent.slice(0, 8).map((j) => (
                    <li key={j.id} className="flex items-center gap-2 text-xs">
                      <span className={`size-1.5 rounded-full shrink-0 ${STATUS_DOT[j.status]}`} />
                      <span
                        className="flex-1 truncate"
                        title={j.error ?? undefined}
                      >
                        {j.title}
                      </span>
                      <span className="text-[10px] text-[var(--muted-foreground)] uppercase tracking-wide">
                        {j.status === "failed" ? "fail" : j.status === "canceled" ? "cancel" : "ok"}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {idle && recent.length === 0 && (
              <div className="px-3.5 py-4 text-xs text-[var(--muted-foreground)] text-center">
                No jobs yet. Ingest something to see it here.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
