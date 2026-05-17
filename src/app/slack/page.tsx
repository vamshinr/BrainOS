"use client";

import { FormEvent, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { DEPARTMENTS } from "@/lib/types";

type Result = Record<string, unknown> | null;

export default function SlackPage() {
  const [health, setHealth] = useState<Result>(null);
  const [channelId, setChannelId] = useState("");
  const [threadTs, setThreadTs] = useState("");
  const [department, setDepartment] = useState("engineering");
  const [question, setQuestion] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [canvasTitle, setCanvasTitle] = useState("Engineering Operational Memory");
  const [canvasDepartment, setCanvasDepartment] = useState("engineering");
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState<Result>(null);

  async function loadHealth() {
    const res = await fetch("/api/slack/health", { cache: "no-store" });
    setHealth(await res.json());
  }

  useEffect(() => {
    let cancelled = false;
    fetch("/api/slack/health", { cache: "no-store" })
      .then((res) => res.json())
      .then((data) => {
        if (!cancelled) setHealth(data);
      })
      .catch((e) => {
        if (!cancelled) setHealth({ error: String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function postJson(path: string, body: Record<string, unknown>) {
    setBusy(path);
    setResult(null);
    try {
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setResult(await res.json());
    } finally {
      setBusy("");
      loadHealth().catch(() => {});
    }
  }

  async function mapChannel(e: FormEvent) {
    e.preventDefault();
    await postJson("/api/slack/channel-map", { channel_id: channelId, department });
  }

  async function ingestThread(e: FormEvent) {
    e.preventDefault();
    await postJson("/api/slack/ingest-thread", {
      channel_id: channelId,
      thread_ts: threadTs,
      department,
    });
  }

  async function ingestChannel(e: FormEvent) {
    e.preventDefault();
    await postJson("/api/slack/ingest-channel", {
      channel_id: channelId,
      department,
      limit: 50,
    });
  }

  async function searchIngest(e: FormEvent) {
    e.preventDefault();
    await postJson("/api/slack/search-ingest", {
      channel_id: channelId || undefined,
      query: searchQuery,
      department,
      limit: 25,
    });
  }

  async function ask(e: FormEvent) {
    e.preventDefault();
    await postJson("/api/slack/ask", {
      channel_id: channelId,
      question,
      department,
      send_to_slack: false,
    });
  }

  async function askAndPost(e: FormEvent) {
    e.preventDefault();
    await postJson("/api/slack/ask", {
      channel_id: channelId,
      question,
      department,
      send_to_slack: true,
    });
  }

  async function exportCanvas(e: FormEvent) {
    e.preventDefault();
    setBusy("canvas");
    setResult(null);
    try {
      const skillsRes = await fetch(`/api/skills?department=${canvasDepartment}`, { cache: "no-store" });
      const markdown = await skillsRes.text();
      const res = await fetch("/api/slack/canvas", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: canvasTitle,
          department: canvasDepartment,
          markdown,
        }),
      });
      setResult(await res.json());
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="px-4 sm:px-6 md:px-10 py-6 md:py-10 max-w-6xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Slack MCP
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">
        Slack-native company memory.
      </h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-3xl">
        Connect approved Slack channels to BrainOS, ingest useful threads, answer with grounded
        company knowledge, and export department skills to Slack canvases.
      </p>

      <section className="mt-6 rounded-lg border bg-[var(--card)] p-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h2 className="font-semibold">Connection</h2>
            <p className="text-sm text-[var(--muted-foreground)]">
              Uses `SLACK_MCP_ACCESS_TOKEN` and `SLACK_MCP_APP_ID` from the Python backend.
            </p>
          </div>
          <button
            onClick={loadHealth}
            className="rounded-md border px-3 py-2 text-sm hover:bg-[var(--muted)]"
          >
            Refresh
          </button>
        </div>
        <pre className="mt-3 max-h-52 overflow-auto rounded bg-[var(--muted)]/40 p-3 text-[11px]">
          {JSON.stringify(health, null, 2)}
        </pre>
      </section>

      <RealtimeDecisionAlerts health={health} />

      <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-4">
        <ControlCard title="Shared Slack Context">
          <LabeledInput label="Channel ID" value={channelId} onChange={setChannelId} placeholder="C1234567890" />
          <label className="block text-xs text-[var(--muted-foreground)]">
            Department
            <select
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm text-[var(--foreground)]"
            >
              {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <form onSubmit={mapChannel}>
            <button className="mt-3 rounded-md border px-3 py-2 text-sm hover:bg-[var(--muted)]">
              Save channel mapping
            </button>
          </form>
        </ControlCard>

        <ControlCard title="Ingest Thread">
          <LabeledInput label="Thread timestamp" value={threadTs} onChange={setThreadTs} placeholder="1710000000.000000" />
          <form onSubmit={ingestThread}>
            <button className="mt-3 rounded-md bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)]">
              Ingest thread
            </button>
          </form>
        </ControlCard>

        <ControlCard title="Ingest Channel Window">
          <p className="text-sm text-[var(--muted-foreground)]">
            Reads the latest 50 messages from the selected channel and sends them through BrainOS extraction.
          </p>
          <form onSubmit={ingestChannel}>
            <button className="mt-3 rounded-md bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)]">
              Ingest channel
            </button>
          </form>
        </ControlCard>

        <ControlCard title="Search And Ingest">
          <LabeledInput label="Slack search query" value={searchQuery} onChange={setSearchQuery} placeholder="billing-svc handoff" />
          <form onSubmit={searchIngest}>
            <button className="mt-3 rounded-md bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)]">
              Search ingest
            </button>
          </form>
        </ControlCard>

        <ControlCard title="Ask BrainOS From Slack Context">
          <LabeledInput label="Question" value={question} onChange={setQuestion} placeholder="Who owns billing-svc now?" />
          <form className="mt-3 flex gap-2" onSubmit={ask}>
            <button className="rounded-md bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)]">
              Preview answer
            </button>
            <button
              type="button"
              onClick={askAndPost}
              className="rounded-md border px-3 py-2 text-sm hover:bg-[var(--muted)]"
            >
              Post to Slack
            </button>
          </form>
        </ControlCard>

        <ControlCard title="Export Skill To Canvas">
          <LabeledInput label="Canvas title" value={canvasTitle} onChange={setCanvasTitle} placeholder="Engineering Operational Memory" />
          <label className="mt-3 block text-xs text-[var(--muted-foreground)]">
            Skill department
            <select
              value={canvasDepartment}
              onChange={(e) => setCanvasDepartment(e.target.value)}
              className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm text-[var(--foreground)]"
            >
              {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>
          <form onSubmit={exportCanvas}>
            <button className="mt-3 rounded-md bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)]">
              Export canvas
            </button>
          </form>
        </ControlCard>
      </div>

      <section className="mt-6 rounded-lg border bg-[var(--card)] p-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Last Result</h2>
          {busy && <span className="text-xs text-[var(--muted-foreground)]">Running {busy}...</span>}
        </div>
        <pre className="mt-3 max-h-[480px] overflow-auto rounded bg-[var(--muted)]/40 p-3 text-[11px]">
          {result ? JSON.stringify(result, null, 2) : "No action run yet."}
        </pre>
      </section>
    </div>
  );
}

function RealtimeDecisionAlerts({ health }: { health: Result }) {
  const realtime = stringList(health?.realtime_ingest_channels);
  const alertChannels = stringList(health?.ceo_decision_alert_channels);
  const channelMap = recordOfStrings(health?.channel_map);
  const mapped = Object.entries(channelMap);

  return (
    <section className="mt-6 rounded-lg border bg-[var(--card)] p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-semibold">Realtime Decision Alerts</h2>
          <p className="mt-1 max-w-2xl text-sm text-[var(--muted-foreground)]">
            Slack message events in realtime ingest channels are queued into BrainOS. Channels also listed for CEO alerts can raise high-confidence decision popups.
          </p>
        </div>
        <div className="flex flex-wrap gap-2 text-[11px]">
          <StatusPill active={Boolean(health?.realtime_ingest_enabled)} label="Realtime ingest" />
          <StatusPill active={Boolean(health?.ceo_decision_alerts_enabled)} label="CEO alerts" />
        </div>
      </div>

      <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
        <ConfigList title="Realtime ingest" items={realtime} empty="Set SLACK_REALTIME_INGEST_CHANNELS" />
        <ConfigList title="CEO alert channels" items={alertChannels} empty="Set SLACK_CEO_DECISION_ALERT_CHANNELS" />
        <div className="rounded-md border bg-[var(--background)]/40 p-3">
          <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
            Channel map
          </div>
          {mapped.length === 0 ? (
            <p className="mt-2 text-xs text-[var(--muted-foreground)]">No mapped channels yet.</p>
          ) : (
            <ul className="mt-2 space-y-1.5 text-xs">
              {mapped.slice(0, 6).map(([channel, dept]) => (
                <li key={channel} className="flex items-center justify-between gap-3">
                  <span className="font-mono truncate">{channel}</span>
                  <span className="text-[var(--muted-foreground)]">{dept}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}

function StatusPill({ active, label }: { active: boolean; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 ${
      active
        ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
        : "border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)]"
    }`}>
      <span className={`size-1.5 rounded-full ${active ? "bg-emerald-500" : "bg-zinc-400"}`} />
      {label}
    </span>
  );
}

function ConfigList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <div className="rounded-md border bg-[var(--background)]/40 p-3">
      <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
        {title}
      </div>
      {items.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--muted-foreground)]">{empty}</p>
      ) : (
        <ul className="mt-2 space-y-1.5 text-xs">
          {items.map((item) => (
            <li key={item} className="font-mono">{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function recordOfStrings(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const out: Record<string, string> = {};
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === "string") out[key] = item;
  }
  return out;
}

function ControlCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border bg-[var(--card)] p-4">
      <h2 className="mb-3 font-semibold">{title}</h2>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <label className="block text-xs text-[var(--muted-foreground)]">
      {label}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm text-[var(--foreground)]"
      />
    </label>
  );
}
