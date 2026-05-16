"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

type Path = "demo" | "slack" | "paste";
type Step = 1 | 2 | 3 | 4;

type SeedEvent =
  | { type: "start"; total: number }
  | { type: "source:start"; index: number; title: string; kind: string }
  | { type: "source:done"; index: number; title: string; units: number; entities: number }
  | { type: "source:error"; index: number; error: string }
  | { type: "done"; totalUnits: number; totalEntities: number };

type Channel = {
  id: string;
  name: string;
  is_member?: boolean;
  is_private?: boolean;
  num_members?: number | null;
};

type AnswerResult = {
  answer: string;
  used?: { sourceTitle?: string; statement?: string }[];
  retrieved_texts?: string[];
  feedback?: { confidence?: number; grounded?: boolean; rationale?: string } | null;
} | null;

const SUGGESTED_QUESTIONS: Record<Path, string[]> = {
  demo: [
    "Who owns the billing service now?",
    "What is our deployment process?",
    "Are there any open disputes I should know about?",
  ],
  slack: [
    "Who owns each service we discussed?",
    "What decisions were made recently?",
    "Are there any open questions or disputes?",
  ],
  paste: [
    "Summarize what you just learned.",
    "Who are the key people mentioned?",
    "What policies or processes appear here?",
  ],
};

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [path, setPath] = useState<Path | null>(null);

  // Slack health
  const [slackHealth, setSlackHealth] = useState<{ configured: boolean; mcp_ok?: boolean } | null>(
    null,
  );
  useEffect(() => {
    fetch("/api/slack/health", { cache: "no-store" })
      .then((r) => r.json())
      .then(setSlackHealth)
      .catch(() => setSlackHealth({ configured: false }));
  }, []);

  // Demo state
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoProgress, setDemoProgress] = useState({
    current: null as string | null,
    done: 0,
    total: 5,
    units: 0,
    entities: 0,
    completed: [] as { title: string; units: number; entities: number }[],
  });
  const [demoErr, setDemoErr] = useState<string | null>(null);

  // Slack state
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [channelsErr, setChannelsErr] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [manualId, setManualId] = useState("");
  const [slackBusy, setSlackBusy] = useState(false);
  const [slackProgress, setSlackProgress] = useState<{
    current: string | null;
    done: number;
    total: number;
    units: number;
    entities: number;
  }>({ current: null, done: 0, total: 0, units: 0, entities: 0 });
  const [slackErr, setSlackErr] = useState<string | null>(null);

  // Paste state
  const [pasteText, setPasteText] = useState("");
  const [pasteBusy, setPasteBusy] = useState(false);
  const [pasteResult, setPasteResult] = useState<{ units: number; entities: number } | null>(null);
  const [pasteErr, setPasteErr] = useState<string | null>(null);

  // Ask state
  const [question, setQuestion] = useState("");
  const [askBusy, setAskBusy] = useState(false);
  const [answer, setAnswer] = useState<AnswerResult>(null);
  const [askErr, setAskErr] = useState<string | null>(null);

  const dotState = useMemo<("done" | "active" | "todo")[]>(() => {
    return [1, 2, 3, 4].map((i) =>
      i < step ? "done" : i === step ? "active" : "todo",
    ) as ("done" | "active" | "todo")[];
  }, [step]);

  function go(next: Step) {
    setStep(next);
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ── Step 2 paths ────────────────────────────────────────────────────────────
  async function runDemo() {
    setDemoBusy(true);
    setDemoErr(null);
    setDemoProgress({ current: null, done: 0, total: 5, units: 0, entities: 0, completed: [] });
    try {
      const res = await fetch("/api/seed", { method: "POST" });
      if (!res.ok || !res.body) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.error ?? `HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev: SeedEvent = JSON.parse(line);
          if (ev.type === "start") {
            setDemoProgress((p) => ({ ...p, total: ev.total }));
          } else if (ev.type === "source:start") {
            setDemoProgress((p) => ({ ...p, current: ev.title }));
          } else if (ev.type === "source:done") {
            setDemoProgress((p) => ({
              ...p,
              done: p.done + 1,
              units: p.units + ev.units,
              entities: p.entities + ev.entities,
              current: null,
              completed: [
                ...p.completed,
                { title: ev.title, units: ev.units, entities: ev.entities },
              ],
            }));
          } else if (ev.type === "source:error") {
            setDemoErr(`Source ${ev.index}: ${ev.error}`);
          }
        }
      }
      router.refresh();
      go(3);
    } catch (e) {
      setDemoErr(e instanceof Error ? e.message : String(e));
    } finally {
      setDemoBusy(false);
    }
  }

  async function loadChannels() {
    setChannels(null);
    setChannelsErr(null);
    try {
      const res = await fetch("/api/slack/channels", { cache: "no-store" });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? json.error ?? `HTTP ${res.status}`);
      setChannels(json.channels ?? []);
    } catch (e) {
      setChannelsErr(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    if (path === "slack" && step === 2 && channels === null) loadChannels();
  }, [path, step, channels]);

  function togglePick(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function runSlackIngest() {
    const ids = Array.from(picked);
    const trimmed = manualId.trim();
    if (trimmed && !ids.includes(trimmed)) ids.push(trimmed);
    if (!ids.length) {
      setSlackErr("Pick at least one channel.");
      return;
    }
    setSlackBusy(true);
    setSlackErr(null);
    setSlackProgress({ current: null, done: 0, total: ids.length, units: 0, entities: 0 });

    for (let i = 0; i < ids.length; i++) {
      const id = ids[i];
      const channel = channels?.find((c) => c.id === id);
      const label = channel ? `#${channel.name}` : id;
      setSlackProgress((p) => ({ ...p, current: label }));
      try {
        const res = await fetch("/api/slack/ingest-channel", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            channel_id: id,
            channel_name: channel?.name,
            limit: 50,
          }),
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.detail ?? json.error ?? `HTTP ${res.status}`);
        const units = json.units_stored ?? 0;
        const entities = json.entities_stored ?? 0;
        setSlackProgress((p) => ({
          ...p,
          done: p.done + 1,
          units: p.units + units,
          entities: p.entities + entities,
          current: null,
        }));
      } catch (e) {
        setSlackErr(`${label}: ${e instanceof Error ? e.message : String(e)}`);
        setSlackBusy(false);
        return;
      }
    }

    setSlackBusy(false);
    router.refresh();
    go(3);
  }

  async function runPaste() {
    if (pasteText.trim().length < 20) {
      setPasteErr("Paste at least a sentence or two.");
      return;
    }
    setPasteBusy(true);
    setPasteErr(null);
    try {
      const res = await fetch("/api/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "other",
          title: "Onboarding paste",
          content: pasteText,
        }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? json.error ?? `HTTP ${res.status}`);
      setPasteResult({ units: json.addedUnits ?? 0, entities: json.addedEntities ?? 0 });
      router.refresh();
      go(3);
    } catch (e) {
      setPasteErr(e instanceof Error ? e.message : String(e));
    } finally {
      setPasteBusy(false);
    }
  }

  // ── Step 3 ──────────────────────────────────────────────────────────────────
  async function ask(q: string) {
    setQuestion(q);
    setAskBusy(true);
    setAskErr(null);
    setAnswer(null);
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? json.error ?? `HTTP ${res.status}`);
      setAnswer(json);
    } catch (e) {
      setAskErr(e instanceof Error ? e.message : String(e));
    } finally {
      setAskBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col">
      <Header dotState={dotState} step={step} />

      <div className="flex-1 grid place-items-start sm:place-items-center px-6 py-10 sm:py-16">
        <div className="w-full max-w-2xl">
          {step === 1 && <StepOne onPick={(p) => { setPath(p); go(2); }} slackHealth={slackHealth} />}
          {step === 2 && path === "demo" && (
            <StepDemo
              busy={demoBusy}
              progress={demoProgress}
              err={demoErr}
              onRun={runDemo}
              onBack={() => go(1)}
            />
          )}
          {step === 2 && path === "slack" && (
            <StepSlack
              channels={channels}
              channelsErr={channelsErr}
              picked={picked}
              onTogglePick={togglePick}
              manualId={manualId}
              onManualIdChange={setManualId}
              busy={slackBusy}
              progress={slackProgress}
              err={slackErr}
              onRun={runSlackIngest}
              onReload={loadChannels}
              onBack={() => go(1)}
            />
          )}
          {step === 2 && path === "paste" && (
            <StepPaste
              text={pasteText}
              onChange={setPasteText}
              busy={pasteBusy}
              result={pasteResult}
              err={pasteErr}
              onRun={runPaste}
              onBack={() => go(1)}
            />
          )}
          {step === 3 && (
            <StepAsk
              suggestions={SUGGESTED_QUESTIONS[path ?? "demo"]}
              question={question}
              onQuestionChange={setQuestion}
              busy={askBusy}
              answer={answer}
              err={askErr}
              onAsk={ask}
              onNext={() => go(4)}
              onSkip={() => go(4)}
            />
          )}
          {step === 4 && <StepFinish />}
        </div>
      </div>

      <footer className="px-6 py-6 flex items-center justify-between text-[11px] text-[var(--muted-foreground)]">
        <Link href="/" className="hover:text-[var(--foreground)]">
          ← Skip onboarding
        </Link>
        <div>
          Step {step} of 4
        </div>
      </footer>
    </div>
  );
}

// ── Components ──────────────────────────────────────────────────────────────

function Header({ dotState, step }: { dotState: ("done" | "active" | "todo")[]; step: Step }) {
  const titles = ["Choose a starting point", "Feed the brain", "Ask the brain", "Connect your agent"];
  return (
    <header className="px-6 pt-8 pb-2">
      <div className="max-w-2xl mx-auto flex items-center gap-3">
        <div className="size-7 rounded-md bg-[var(--accent)] grid place-items-center text-white text-xs font-bold">
          CB
        </div>
        <div className="flex-1">
          <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
            Setup · {titles[step - 1]}
          </div>
        </div>
        <div className="flex items-center gap-1.5">
          {dotState.map((s, i) => (
            <span
              key={i}
              className={`block rounded-full transition-all ${
                s === "active"
                  ? "w-6 h-1.5 bg-[var(--accent)]"
                  : s === "done"
                    ? "w-1.5 h-1.5 bg-[var(--foreground)]"
                    : "w-1.5 h-1.5 bg-[var(--border)]"
              }`}
            />
          ))}
        </div>
      </div>
    </header>
  );
}

function StepOne({
  onPick,
  slackHealth,
}: {
  onPick: (p: Path) => void;
  slackHealth: { configured: boolean; mcp_ok?: boolean } | null;
}) {
  const slackReady = !!(slackHealth?.configured && slackHealth?.mcp_ok);
  return (
    <div>
      <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight">
        Give your AI agents a brain.
      </h1>
      <p className="mt-3 text-[var(--muted-foreground)] max-w-xl">
        BrainOS extracts facts, decisions, and ownership from your scattered
        knowledge — then exports them as a skill file any agent can load. Pick
        how you want to start.
      </p>

      <div className="mt-10 space-y-3">
        <Card
          recommended
          title="Try a demo company"
          subtitle="See it work in 20 seconds. 5 example sources, ~40 facts, full graph."
          glyph="✨"
          onClick={() => onPick("demo")}
        />
        <Card
          title="Connect your Slack"
          subtitle={
            slackReady
              ? "MCP detected — pick channels and pull recent threads."
              : slackHealth
                ? "Slack MCP not configured. Set SLACK_MCP_ACCESS_TOKEN in the backend."
                : "Checking workspace…"
          }
          glyph="💬"
          status={slackReady ? "ready" : slackHealth ? "off" : "loading"}
          disabled={!slackReady}
          onClick={() => slackReady && onPick("slack")}
        />
        <Card
          title="Paste anything"
          subtitle="A Slack thread, a runbook, a meeting note. Fastest custom start."
          glyph="📋"
          onClick={() => onPick("paste")}
        />
      </div>
    </div>
  );
}

function Card({
  title,
  subtitle,
  glyph,
  onClick,
  recommended,
  status,
  disabled,
}: {
  title: string;
  subtitle: string;
  glyph: string;
  onClick: () => void;
  recommended?: boolean;
  status?: "ready" | "off" | "loading";
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`group w-full text-left rounded-xl border bg-[var(--card)] p-5 transition-all ${
        disabled
          ? "opacity-60 cursor-not-allowed"
          : "hover:border-[var(--accent)]/60 hover:-translate-y-0.5 hover:shadow-sm"
      }`}
    >
      <div className="flex items-start gap-4">
        <div className="text-2xl leading-none mt-0.5" aria-hidden>
          {glyph}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="font-semibold">{title}</div>
            {recommended && (
              <span className="rounded-full px-2 py-0.5 text-[10px] font-medium bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30">
                Recommended
              </span>
            )}
            {status === "ready" && (
              <span className="inline-flex items-center gap-1 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                <span className="size-1.5 rounded-full bg-emerald-500 inline-block" /> Connected
              </span>
            )}
            {status === "off" && (
              <span className="text-[10px] font-medium text-[var(--muted-foreground)]">
                Not configured
              </span>
            )}
            {status === "loading" && (
              <span className="text-[10px] font-medium text-[var(--muted-foreground)]">
                Checking…
              </span>
            )}
          </div>
          <div className="mt-1 text-sm text-[var(--muted-foreground)]">{subtitle}</div>
        </div>
        <div className="text-[var(--muted-foreground)] group-hover:text-[var(--foreground)] transition-colors mt-1">
          →
        </div>
      </div>
    </button>
  );
}

function StepDemo({
  busy,
  progress,
  err,
  onRun,
  onBack,
}: {
  busy: boolean;
  progress: {
    current: string | null;
    done: number;
    total: number;
    units: number;
    entities: number;
    completed: { title: string; units: number; entities: number }[];
  };
  err: string | null;
  onRun: () => void;
  onBack: () => void;
}) {
  const started = busy || progress.completed.length > 0;
  return (
    <div>
      <button onClick={onBack} className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] mb-4">
        ← Pick a different starting point
      </button>
      <h1 className="text-3xl font-semibold tracking-tight">
        {started ? "Building your demo brain…" : "Spin up an example company."}
      </h1>
      <p className="mt-3 text-[var(--muted-foreground)] max-w-xl">
        We&apos;ll feed BrainOS five realistic sources — a Slack handoff thread,
        a runbook, an email, a ticket, and a meeting note — and build the graph
        live.
      </p>

      {!started && (
        <button
          onClick={onRun}
          className="mt-8 rounded-md bg-[var(--accent)] text-white px-5 py-3 text-sm font-medium hover:opacity-90"
        >
          Start the demo
        </button>
      )}

      {started && (
        <div className="mt-8 rounded-xl border bg-[var(--card)] p-5">
          <div className="grid grid-cols-3 gap-3 mb-5">
            <Stat label="Sources" value={`${progress.done}/${progress.total}`} />
            <Stat label="Facts" value={progress.units} />
            <Stat label="Entities" value={progress.entities} />
          </div>

          <div className="space-y-2">
            {progress.completed.map((c, i) => (
              <Row key={i} state="done" title={c.title} sub={`${c.units} facts · ${c.entities} entities`} />
            ))}
            {progress.current && (
              <Row state="active" title={progress.current} sub="Extracting…" />
            )}
            {Array.from({ length: Math.max(0, progress.total - progress.done - (progress.current ? 1 : 0)) }).map((_, i) => (
              <Row key={`p${i}`} state="todo" title="…" sub="Queued" />
            ))}
          </div>

          {err && <div className="mt-4 text-xs text-red-600">{err}</div>}
        </div>
      )}
    </div>
  );
}

function StepSlack({
  channels,
  channelsErr,
  picked,
  onTogglePick,
  manualId,
  onManualIdChange,
  busy,
  progress,
  err,
  onRun,
  onReload,
  onBack,
}: {
  channels: Channel[] | null;
  channelsErr: string | null;
  picked: Set<string>;
  onTogglePick: (id: string) => void;
  manualId: string;
  onManualIdChange: (v: string) => void;
  busy: boolean;
  progress: { current: string | null; done: number; total: number; units: number; entities: number };
  err: string | null;
  onRun: () => void;
  onReload: () => void;
  onBack: () => void;
}) {
  const count = picked.size + (manualId.trim() ? 1 : 0);
  return (
    <div>
      <button onClick={onBack} className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] mb-4">
        ← Pick a different starting point
      </button>
      <h1 className="text-3xl font-semibold tracking-tight">Pick channels to learn from.</h1>
      <p className="mt-3 text-[var(--muted-foreground)] max-w-xl">
        We&apos;ll pull the last 50 messages from each and extract atomic
        facts, ownership, and decisions. Nothing is sent back to Slack unless
        you ask.
      </p>

      <div className="mt-8 rounded-xl border bg-[var(--card)] p-2 max-h-80 overflow-y-auto">
        {channels === null && !channelsErr && (
          <div className="px-4 py-6 text-sm text-[var(--muted-foreground)]">Loading channels…</div>
        )}
        {channelsErr && (
          <div className="px-4 py-6 text-sm">
            <div className="text-red-600">{channelsErr}</div>
            <button onClick={onReload} className="mt-2 text-xs underline">
              Retry
            </button>
          </div>
        )}
        {channels && channels.length === 0 && (
          <div className="px-4 py-6 text-sm text-[var(--muted-foreground)]">
            No channels visible to this Slack token. Paste an ID below.
          </div>
        )}
        {channels && channels.length > 0 && (
          <ul>
            {channels.map((c) => {
              const checked = picked.has(c.id);
              return (
                <li key={c.id}>
                  <button
                    onClick={() => onTogglePick(c.id)}
                    className={`w-full flex items-center justify-between gap-3 px-3 py-2.5 rounded-lg text-left text-sm hover:bg-[var(--muted)]/50 ${
                      checked ? "bg-[var(--muted)]/60" : ""
                    }`}
                  >
                    <span className="flex items-center gap-3 min-w-0">
                      <span
                        className={`size-4 rounded border grid place-items-center transition-colors ${
                          checked ? "bg-[var(--accent)] border-[var(--accent)]" : "border-[var(--border)]"
                        }`}
                      >
                        {checked && (
                          <svg viewBox="0 0 12 12" className="size-2.5 text-white" fill="none" stroke="currentColor" strokeWidth={2.5}>
                            <path d="M2 6.5L4.5 9 10 3" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        )}
                      </span>
                      <span className="font-medium truncate">{c.is_private ? "🔒 " : "#"}{c.name}</span>
                    </span>
                    <span className="text-[11px] text-[var(--muted-foreground)] shrink-0">
                      {typeof c.num_members === "number" ? `${c.num_members} members` : ""}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="mt-3">
        <label className="block text-[11px] text-[var(--muted-foreground)]">
          Or paste a channel ID
          <input
            value={manualId}
            onChange={(e) => onManualIdChange(e.target.value)}
            placeholder="C0B2ALQLA4F"
            className="mt-1 w-full rounded-md border bg-transparent px-3 py-2 text-sm font-mono"
          />
        </label>
      </div>

      {busy && (
        <div className="mt-6 rounded-xl border bg-[var(--card)] p-4 text-sm">
          <div className="flex items-center justify-between">
            <span>{progress.current ?? "Starting…"}</span>
            <span className="text-[var(--muted-foreground)]">
              {progress.done}/{progress.total}
            </span>
          </div>
          <div className="mt-2 h-1 rounded-full bg-[var(--muted)] overflow-hidden">
            <div
              className="h-full bg-[var(--accent)] transition-all"
              style={{ width: `${(progress.done / Math.max(1, progress.total)) * 100}%` }}
            />
          </div>
          <div className="mt-2 text-[11px] text-[var(--muted-foreground)]">
            {progress.units} facts · {progress.entities} entities so far
          </div>
        </div>
      )}

      {err && <div className="mt-4 text-xs text-red-600">{err}</div>}

      <div className="mt-8 flex items-center gap-3">
        <button
          onClick={onRun}
          disabled={busy || count === 0}
          className="rounded-md bg-[var(--accent)] text-white px-5 py-3 text-sm font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy ? "Pulling…" : count === 0 ? "Pick at least one channel" : `Pull from ${count} channel${count === 1 ? "" : "s"}`}
        </button>
      </div>
    </div>
  );
}

function StepPaste({
  text,
  onChange,
  busy,
  result,
  err,
  onRun,
  onBack,
}: {
  text: string;
  onChange: (v: string) => void;
  busy: boolean;
  result: { units: number; entities: number } | null;
  err: string | null;
  onRun: () => void;
  onBack: () => void;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <div>
      <button onClick={onBack} className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] mb-4">
        ← Pick a different starting point
      </button>
      <h1 className="text-3xl font-semibold tracking-tight">Paste anything your team knows.</h1>
      <p className="mt-3 text-[var(--muted-foreground)] max-w-xl">
        A Slack thread. An old runbook. A meeting note. A ticket. The brain will
        extract atomic facts, names, and relationships — and find conflicts when
        you add more.
      </p>

      <textarea
        ref={ref}
        value={text}
        onChange={(e) => onChange(e.target.value)}
        rows={12}
        placeholder={`Bob: hey team, just confirming Alice is still owning billing-svc end-to-end?\nAlice: confirming, plus the Stripe webhook retry logic.\nNick: ack — but heads up, after Q2 Bob and I are taking it over.`}
        className="mt-8 w-full rounded-xl border bg-[var(--card)] px-4 py-3 text-sm font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30"
      />

      <div className="mt-2 flex items-center justify-between text-[11px] text-[var(--muted-foreground)]">
        <span>{text.length} chars</span>
        <span>Tip: paste real Slack threads, including timestamps and authors.</span>
      </div>

      {err && <div className="mt-4 text-xs text-red-600">{err}</div>}
      {result && (
        <div className="mt-4 text-sm">
          Extracted <strong>{result.units}</strong> facts and <strong>{result.entities}</strong> entities.
        </div>
      )}

      <div className="mt-6">
        <button
          onClick={onRun}
          disabled={busy || text.trim().length < 20}
          className="rounded-md bg-[var(--accent)] text-white px-5 py-3 text-sm font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {busy ? "Extracting knowledge…" : "Extract knowledge"}
        </button>
      </div>
    </div>
  );
}

function StepAsk({
  suggestions,
  question,
  onQuestionChange,
  busy,
  answer,
  err,
  onAsk,
  onNext,
  onSkip,
}: {
  suggestions: string[];
  question: string;
  onQuestionChange: (v: string) => void;
  busy: boolean;
  answer: AnswerResult;
  err: string | null;
  onAsk: (q: string) => void;
  onNext: () => void;
  onSkip: () => void;
}) {
  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">Your brain is awake. Try it.</h1>
      <p className="mt-3 text-[var(--muted-foreground)] max-w-xl">
        Ask anything you taught it. Every answer is grounded — you&apos;ll see
        the exact sentences the brain used and a confidence score.
      </p>

      <div className="mt-8 space-y-2">
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => onAsk(s)}
            disabled={busy}
            className="w-full text-left rounded-lg border bg-[var(--card)] px-4 py-3 text-sm hover:border-[var(--accent)]/60 hover:bg-[var(--muted)]/30 transition-colors disabled:opacity-50"
          >
            <span className="text-[var(--muted-foreground)] mr-2">→</span>
            {s}
          </button>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (question.trim()) onAsk(question);
        }}
        className="mt-4 flex gap-2"
      >
        <input
          value={question}
          onChange={(e) => onQuestionChange(e.target.value)}
          placeholder="Or type your own…"
          className="flex-1 rounded-md border bg-[var(--card)] px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/30"
        />
        <button
          type="submit"
          disabled={busy || !question.trim()}
          className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-3 text-sm font-medium disabled:opacity-40"
        >
          Ask
        </button>
      </form>

      {busy && (
        <div className="mt-6 text-sm text-[var(--muted-foreground)]">Thinking…</div>
      )}

      {err && <div className="mt-4 text-xs text-red-600">{err}</div>}

      {answer && (
        <div className="mt-6 rounded-xl border bg-[var(--card)] p-5">
          <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
            Answer
          </div>
          <div className="text-sm leading-relaxed whitespace-pre-wrap">
            {answer.answer}
          </div>
          {answer.feedback && (
            <div className="mt-4 flex items-center gap-2 text-[11px]">
              <span
                className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ${
                  answer.feedback.grounded
                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
                    : "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                }`}
              >
                <span
                  className={`size-1.5 rounded-full ${
                    answer.feedback.grounded ? "bg-emerald-500" : "bg-amber-500"
                  }`}
                />
                {answer.feedback.grounded ? "Grounded" : "Needs review"}
              </span>
              {typeof answer.feedback.confidence === "number" && (
                <span className="text-[var(--muted-foreground)]">
                  {answer.feedback.confidence.toFixed(2)} confidence
                </span>
              )}
            </div>
          )}
          {answer.retrieved_texts && answer.retrieved_texts.length > 0 && (
            <details className="mt-4">
              <summary className="cursor-pointer text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
                {answer.retrieved_texts.length} citations
              </summary>
              <ul className="mt-2 space-y-1.5 text-xs">
                {answer.retrieved_texts.slice(0, 5).map((t, i) => (
                  <li key={i} className="rounded bg-[var(--muted)]/40 px-3 py-2 text-[var(--muted-foreground)]">
                    {t}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <div className="mt-10 flex items-center justify-between">
        <button onClick={onSkip} className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
          Skip — go to dashboard
        </button>
        <button
          onClick={onNext}
          disabled={!answer}
          className="rounded-md bg-[var(--accent)] text-white px-5 py-3 text-sm font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Continue →
        </button>
      </div>
    </div>
  );
}

function StepFinish() {
  const [copied, setCopied] = useState(false);
  const [skills, setSkills] = useState<string | null>(null);
  const [counts, setCounts] = useState<{ units: number; entities: number; sources: number } | null>(null);

  useEffect(() => {
    fetch("/api/skills")
      .then((r) => r.text())
      .then(setSkills)
      .catch(() => setSkills(null));
    fetch("/api/state")
      .then((r) => r.json())
      .then((s) =>
        setCounts({
          units: (s.units ?? []).filter((u: { stale?: boolean; supersededBy?: string }) => !u.stale && !u.supersededBy).length,
          entities: (s.entities ?? []).length,
          sources: (s.sources ?? []).length,
        }),
      )
      .catch(() => setCounts(null));
  }, []);

  async function copy() {
    if (!skills) return;
    await navigator.clipboard.writeText(skills);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div>
      <h1 className="text-3xl font-semibold tracking-tight">
        Your brain is ready. Plug it into your agent.
      </h1>
      <p className="mt-3 text-[var(--muted-foreground)] max-w-xl">
        BrainOS compiles everything it knows into <code className="font-mono text-xs">SKILLS.md</code>
        — a self-contained file any AI agent can load to operate inside your
        company.
      </p>

      <div className="mt-8 rounded-xl border bg-[var(--card)] p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="font-semibold">SKILLS.md</div>
            {counts && (
              <div className="mt-1 text-xs text-[var(--muted-foreground)]">
                {counts.units} facts · {counts.entities} entities · {counts.sources} sources
              </div>
            )}
          </div>
          <div className="flex gap-2 shrink-0">
            <button
              onClick={copy}
              disabled={!skills}
              className="rounded-md border px-3 py-2 text-xs hover:bg-[var(--muted)] disabled:opacity-40"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
            <a
              href="/api/skills"
              download="SKILLS.md"
              className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-3 py-2 text-xs font-medium"
            >
              Download
            </a>
          </div>
        </div>

        {skills && (
          <pre className="mt-4 max-h-48 overflow-auto rounded bg-[var(--muted)]/40 p-3 text-[11px] leading-relaxed">
            {skills.slice(0, 1200)}
            {skills.length > 1200 ? "\n…" : ""}
          </pre>
        )}
      </div>

      <div className="mt-8">
        <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
          Use it with
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Recipe
            title="Claude Code"
            sub="Save as CLAUDE.md"
            href="https://docs.claude.com/en/docs/claude-code/memory"
          />
          <Recipe
            title="Cursor"
            sub="Save as .cursorrules"
            href="https://cursor.com/docs/context/rules"
          />
          <Recipe
            title="ChatGPT"
            sub="Paste as system prompt"
          />
          <Recipe
            title="MCP server"
            sub="Coming soon"
            disabled
          />
        </div>
      </div>

      <div className="mt-10 flex items-center gap-3">
        <Link
          href="/"
          className="rounded-md bg-[var(--accent)] text-white px-5 py-3 text-sm font-medium hover:opacity-90"
        >
          Open Brain dashboard →
        </Link>
        <Link
          href="/ingest"
          className="rounded-md border px-5 py-3 text-sm hover:bg-[var(--muted)]"
        >
          Add more knowledge
        </Link>
      </div>
    </div>
  );
}

function Recipe({
  title,
  sub,
  href,
  disabled,
}: {
  title: string;
  sub: string;
  href?: string;
  disabled?: boolean;
}) {
  const inner = (
    <div
      className={`rounded-lg border bg-[var(--card)] px-3 py-3 text-left transition-colors ${
        disabled ? "opacity-50" : "hover:border-[var(--accent)]/60"
      }`}
    >
      <div className="text-sm font-medium">{title}</div>
      <div className="text-[11px] text-[var(--muted-foreground)] mt-0.5">{sub}</div>
    </div>
  );
  if (disabled || !href) return <div>{inner}</div>;
  return (
    <a href={href} target="_blank" rel="noreferrer" className="block">
      {inner}
    </a>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function Row({
  state,
  title,
  sub,
}: {
  state: "todo" | "active" | "done";
  title: string;
  sub: string;
}) {
  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded-md">
      <span
        className={`size-2 rounded-full ${
          state === "done"
            ? "bg-emerald-500"
            : state === "active"
              ? "bg-[var(--accent)] animate-pulse"
              : "bg-[var(--border)]"
        }`}
      />
      <div className="flex-1 min-w-0">
        <div className={`text-sm truncate ${state === "todo" ? "text-[var(--muted-foreground)]" : ""}`}>
          {title}
        </div>
      </div>
      <div className="text-[11px] text-[var(--muted-foreground)] shrink-0">{sub}</div>
    </div>
  );
}
