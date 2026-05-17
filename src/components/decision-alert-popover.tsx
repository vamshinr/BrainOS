"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Bell, Check, ExternalLink, X } from "lucide-react";

interface DecisionAlert {
  id: string;
  unitId?: string;
  statement: string;
  subject?: string;
  confidence: number;
  sourceId?: string;
  sourceTitle?: string;
  channelId?: string;
  channelName?: string;
  threadTs?: string;
  evidenceQuote?: string;
  createdAt: string;
  status: string;
}

export function DecisionAlertPopover() {
  const [alerts, setAlerts] = useState<DecisionAlert[]>([]);
  const [connected, setConnected] = useState(false);
  const current = alerts[0] ?? null;

  const applyEvent = useCallback((data: {
    event: string;
    alerts?: DecisionAlert[];
    alert?: DecisionAlert;
  }) => {
    if (data.event === "snapshot" && data.alerts) {
      setAlerts(data.alerts.filter((a) => a.status === "open"));
      return;
    }

    if (!data.alert) return;
    const alert = data.alert;
    setAlerts((prev) => {
      const next = prev.filter((a) => a.id !== alert.id);
      if (data.event === "decision_alert.created" && alert.status === "open") {
        return [alert, ...next].slice(0, 20);
      }
      return next;
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    let es: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    fetch("/api/decision-alerts", { cache: "no-store" })
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) {
          setAlerts((data.alerts ?? []).filter((a: DecisionAlert) => a.status === "open"));
        }
      })
      .catch(() => {});

    const connect = () => {
      if (cancelled) return;
      es = new EventSource("/api/decision-alerts/stream");
      es.onopen = () => setConnected(true);
      es.onmessage = (ev) => {
        try {
          applyEvent(JSON.parse(ev.data));
        } catch {
          // Ignore malformed frames and keepalive comments.
        }
      };
      es.onerror = () => {
        setConnected(false);
        es?.close();
        if (!cancelled) retryTimer = setTimeout(connect, 3000);
      };
    };

    connect();
    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      es?.close();
    };
  }, [applyEvent]);

  const sourceLabel = useMemo(() => {
    if (!current) return "";
    const channel = current.channelName || current.channelId || "Slack";
    if (current.threadTs) return `${channel} · ${current.threadTs}`;
    return channel;
  }, [current]);

  async function updateAlert(id: string, action: "ack" | "dismiss") {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
    try {
      await fetch(`/api/decision-alerts/${id}/${action}`, { method: "POST" });
    } catch {
      // The next SSE snapshot/reload will restore the alert if persistence failed.
    }
  }

  if (!current) {
    return (
      <div
        className="fixed bottom-16 right-4 z-40 hidden sm:flex items-center gap-2 rounded-full border bg-[var(--card)] px-3 py-2 text-xs text-[var(--muted-foreground)] shadow-md"
        title={connected ? "CEO decision alerts live" : "CEO decision alerts disconnected"}
      >
        <span className={`size-2 rounded-full ${connected ? "bg-emerald-500" : "bg-zinc-400"}`} />
        Decisions
      </div>
    );
  }

  return (
    <section className="fixed bottom-16 right-4 z-50 w-[min(360px,calc(100vw-2rem))] rounded-lg border bg-[var(--card)] shadow-xl overflow-hidden">
      <div className="flex items-start gap-3 border-b px-3.5 py-3">
        <div className="mt-0.5 grid size-8 place-items-center rounded-md bg-[var(--accent)]/10 text-[var(--accent)]">
          <Bell size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
              CEO Decision
            </div>
            {alerts.length > 1 && (
              <span className="rounded-full bg-[var(--muted)] px-2 py-0.5 text-[10px] text-[var(--muted-foreground)]">
                +{alerts.length - 1}
              </span>
            )}
          </div>
          <h2 className="mt-1 text-sm font-semibold leading-snug">
            {current.subject || "Key decision"}
          </h2>
        </div>
      </div>

      <div className="px-3.5 py-3">
        <p className="text-sm leading-snug">{current.statement}</p>
        {current.evidenceQuote && (
          <p className="mt-2 line-clamp-2 text-xs leading-snug text-[var(--muted-foreground)]">
            {current.evidenceQuote}
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
          <span>conf {current.confidence.toFixed(2)}</span>
          <span>source {current.sourceId || "unknown"}</span>
          <span>{sourceLabel}</span>
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 border-t bg-[var(--background)]/60 px-3.5 py-2.5">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs hover:bg-[var(--muted)]/60"
        >
          <ExternalLink size={13} />
          View in Brain
        </Link>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => updateAlert(current.id, "dismiss")}
            className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs hover:bg-[var(--muted)]/60"
          >
            <X size={13} />
            Dismiss
          </button>
          <button
            type="button"
            onClick={() => updateAlert(current.id, "ack")}
            className="inline-flex items-center gap-1.5 rounded-md bg-[var(--foreground)] px-2.5 py-1.5 text-xs text-[var(--background)] hover:opacity-90"
          >
            <Check size={13} />
            Acknowledge
          </button>
        </div>
      </div>
    </section>
  );
}
