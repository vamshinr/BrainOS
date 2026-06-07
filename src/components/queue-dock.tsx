"use client";

import { useEffect, useRef, useState, useCallback } from "react";

type JobStatus = "queued" | "running" | "completed" | "failed" | "canceled";
type JobKind = "ingest_text" | "ingest_file" | string;

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
  active: Job[];
  queued: Job[];
  recent: Job[];
}

const KIND_LABEL: Record<string, string> = {
  ingest_text: "text",
  ingest_file: "file",
};

const STATUS_DOT: Record<JobStatus, string> = {
  queued: "bg-zinc-400",
  running: "bg-blue-500 animate-pulse",
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  canceled: "bg-zinc-500",
};

const EMPTY: Snapshot = { active: [], queued: [], recent: [] };

export function QueueDock() {
  const [snap, setSnap] = useState<Snapshot>(EMPTY);
  const [open, setOpen] = useState(false);
  const [connected, setConnected] = useState(false);
  const lastFinishedAt = useRef<string | null>(null);

  // When a job finishes, tell interested pages (home, /graph) to re-fetch.
  // Deduplicated by the newest finishedAt so the same finish never fires twice.
  const notifyFinished = useCallback((snapshot: Snapshot) => {
    const newest = snapshot.recent.find(
      (j) => j.status === "completed" || j.status === "failed",
    );
    const at = newest?.finishedAt ?? null;
    if (!at || at === lastFinishedAt.current) return;
    lastFinishedAt.current = at;
    window.dispatchEvent(new CustomEvent("mnemosyne:ingested"));
  }, []);

  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const apply = (data: { event?: string; snapshot?: Snapshot }) => {
      if (data.snapshot) {
        setSnap(data.snapshot);
        notifyFinished(data.snapshot);
      }
    };

    const connect = () => {
      if (cancelled) return;
      es = new EventSource("/api/jobs/stream");
      es.onopen = () => setConnected(true);
      es.onmessage = (ev) => {
        try {
          apply(JSON.parse(ev.data));
        } catch {
          /* ignore heartbeats / malformed frames */
        }
      };
      es.onerror = () => {
        setConnected(false);
        es?.close();
        if (!cancelled) retryTimer = setTimeout(connect, 3000);
      };
    };

    fetch("/api/jobs", { cache: "no-store" })
      .then((r) => r.json())
      .then((s: Snapshot) => !cancelled && setSnap(s))
      .catch(() => {});

    connect();
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
    };
  }, [notifyFinished]);

  const { active, queued, recent } = snap;
  const idle = active.length === 0 && queued.length === 0;

  const cancel = async (id: string) => {
    try {
      await fetch(`/api/jobs/${id}`, { method: "DELETE" });
    } catch {
      /* best effort */
    }
  };

  // Idle + collapsed → small floating badge.
  if (idle && !open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-4 right-4 z-50 size-10 rounded-full bg-[var(--card)] border shadow-lg flex items-center justify-center hover:bg-[var(--muted)]/60 transition-colors group"
        title={connected ? "Queue · idle (click for history)" : "Queue · disconnected"}
        aria-label="Open queue"
      >
        <span className={`size-2.5 rounded-full ${connected ? "bg-emerald-500" : "bg-zinc-400"}`} />
        {recent.length > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-[var(--muted)] text-[10px] font-mono leading-none flex items-center justify-center text-[var(--muted-foreground)] group-hover:bg-[var(--accent)]/15 group-hover:text-[var(--accent)] transition-colors">
            {recent.length > 99 ? "99+" : recent.length}
          </span>
        )}
      </button>
    );
  }

  const headerLabel =
    active.length === 1
      ? `Processing · ${KIND_LABEL[active[0].kind] ?? active[0].kind}`
      : active.length > 1
        ? "Processing"
        : queued.length > 0
          ? "Queued"
          : "Queue";
  const headerTitle =
    active.length === 1
      ? active[0].title
      : active.length > 1
        ? `${active.length} running`
        : queued.length > 0
          ? `${queued.length} waiting`
          : "Idle";

  return (
    <div className="fixed bottom-4 right-4 z-50 w-[320px]">
      <div className="rounded-lg border bg-[var(--card)] shadow-lg overflow-hidden">
        <button
          onClick={() => setOpen((o) => !o)}
          className="w-full flex items-center gap-2.5 px-3.5 py-2.5 hover:bg-[var(--muted)]/40 transition-colors text-left"
        >
          <span
            className={`size-2 rounded-full shrink-0 ${
              active.length > 0 ? STATUS_DOT.running : connected ? "bg-emerald-500" : "bg-zinc-400"
            }`}
            title={connected ? "live" : "disconnected"}
          />
          <div className="flex-1 min-w-0">
            <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
              {headerLabel}
            </div>
            <div className="text-sm font-medium truncate">{headerTitle}</div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {queued.length > 0 && (
              <span className="text-[11px] font-mono text-[var(--muted-foreground)]">
                +{queued.length}
              </span>
            )}
            <span className={`text-[var(--muted-foreground)] transition-transform ${open ? "rotate-180" : ""}`}>
              ⌃
            </span>
          </div>
        </button>

        {/* Per-active progress bars, always visible */}
        {active.map((job) => (
          <div key={job.id} className="px-3.5 pb-2">
            {active.length > 1 && (
              <div className="text-[11px] text-[var(--muted-foreground)] truncate mb-1">{job.title}</div>
            )}
            <div className="h-1 rounded-full bg-[var(--muted)] overflow-hidden">
              <div
                className="h-full bg-[var(--accent)] transition-all"
                style={{ width: `${Math.max(4, Math.round(job.progress * 100))}%` }}
              />
            </div>
            {job.step && (
              <div className="mt-1.5 text-[11px] text-[var(--muted-foreground)] truncate">{job.step}</div>
            )}
          </div>
        ))}

        {open && (
          <div className="border-t bg-[var(--background)]/60 max-h-[60vh] overflow-y-auto">
            {queued.length > 0 && (
              <div className="px-3.5 py-2.5">
                <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
                  Queued
                </div>
                <ul className="space-y-1">
                  {queued.map((j, i) => (
                    <li key={j.id} className="flex items-center gap-2 text-xs group">
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
                      <span className="flex-1 truncate" title={j.error ?? undefined}>
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
