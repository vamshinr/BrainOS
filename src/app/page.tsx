"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ResetBrainModal } from "@/components/reset-brain-modal";

type AskResponse = {
  answer?: string;
  draft_answer?: string;
  retrieved_texts?: string[];
  used?: string[];
  retrieval_mode?: string;
  latency_ms?: number;
  feedback?: {
    confidence?: number;
    grounded?: boolean;
    feedback?: string;
  };
  error?: string;
  detail?: string;
};

type ActivityKind = "slack" | "doc" | "other";

type ActivityItem = {
  id: string;
  kind: ActivityKind;
  title: string;
  subtitle?: string;
  capturedAt: string;
  channelId?: string;
  channelName?: string;
  text?: string;
};

type ChannelInfo = { id: string; name: string };

type DashboardState = {
  docs: number;
  slackChannels: string[];
  slackMessages: number;
  units: number;
  entities: number;
  decisions: number;
  lastActivityAt: string | null;
  activity: ActivityItem[];
};

const SUGGESTIONS = [
  "What did people ask about recently?",
  "What's the latest discussion in Slack?",
  "Who owns billing?",
  "Summarize the most recent conversations",
];

export default function HomePage() {
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [dashboard, setDashboard] = useState<DashboardState | null>(null);
  const [channelNames, setChannelNames] = useState<Record<string, string>>({});
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Resolve channel IDs → human names. Refreshes occasionally so newly mapped
  // channels show up with their real names.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const r = await fetch("/api/slack/channels", { cache: "no-store" });
        const j = await r.json();
        if (cancelled) return;
        const map: Record<string, string> = {};
        for (const c of (j.channels || []) as ChannelInfo[]) {
          map[c.id] = c.name;
        }
        setChannelNames(map);
      } catch {
        // keep last
      }
    };
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Pull live dashboard state every 5s.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const stateRes = await fetch("/api/state", { cache: "no-store" });
        const state = await stateRes.json();
        if (cancelled) return;
        const sources = state?.sources ?? [];
        const units = state?.units ?? [];
        const entities = state?.entities ?? [];
        const slackSources = sources.filter(
          (s: { kind?: string }) => s.kind === "slack",
        );
        const docSources = sources.filter(
          (s: { kind?: string }) =>
            s.kind &&
            ["doc", "pdf", "file", "text", "code", "image"].includes(s.kind),
        );
        const slackChannels = Array.from(
          new Set(
            slackSources
              .map((s: { channelId?: string }) => s.channelId)
              .filter(Boolean) as string[],
          ),
        );
        const decisions = units.filter(
          (u: { kind?: string; stale?: boolean; supersededBy?: string }) =>
            u.kind === "decision" && !u.stale && !u.supersededBy,
        );
        const activity: ActivityItem[] = sources
          .slice()
          .sort(
            (
              a: { capturedAt?: string },
              b: { capturedAt?: string },
            ) =>
              (a.capturedAt || "") < (b.capturedAt || "") ? 1 : -1,
          )
          // Only keep things a customer cares about: real Slack realtime
          // messages (title starts with "Slack Realtime:") and documents.
          // The thread/search MCP responses get stored as Slack-kind sources
          // with raw JSON content and just clutter the feed.
          .filter((s: { kind?: string; title?: string }) => {
            if (s.kind === "slack") {
              return (s.title || "").startsWith("Slack Realtime:");
            }
            return s.kind && ["doc", "pdf", "file", "text", "code", "image"].includes(s.kind);
          })
          .slice(0, 8)
          .map(
            (s: {
              id: string;
              kind?: string;
              title?: string;
              channelId?: string;
              capturedAt?: string;
              content?: string;
            }) => {
              const kind: ActivityKind =
                s.kind === "slack"
                  ? "slack"
                  : s.kind &&
                      ["doc", "pdf", "file", "text", "code", "image"].includes(
                        s.kind,
                      )
                    ? "doc"
                    : "other";
              const text =
                kind === "slack" ? extractSlackText(s.content || "") : undefined;
              return {
                id: s.id,
                kind,
                title: s.title || "Untitled",
                subtitle: kind === "doc" ? s.kind : undefined,
                capturedAt: s.capturedAt || "",
                channelId: s.channelId,
                channelName: undefined,
                text,
              };
            },
          );
        const lastActivityAt = activity[0]?.capturedAt || null;
        setDashboard({
          docs: docSources.length,
          slackChannels,
          slackMessages: slackSources.length,
          units: units.length,
          entities: entities.length,
          decisions: decisions.length,
          lastActivityAt,
          activity,
        });
      } catch {
        // keep last state
      }
    };
    load();
    const id = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const ask = useCallback(
    async (q: string) => {
      const trimmed = q.trim();
      if (!trimmed || asking) return;
      setAsking(true);
      setAnswer(null);
      try {
        const res = await fetch("/api/ask", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: trimmed }),
        });
        const data = (await res.json()) as AskResponse;
        setAnswer(data);
      } catch (e) {
        setAnswer({ error: String(e) });
      } finally {
        setAsking(false);
      }
    },
    [asking],
  );

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      ask(question);
    }
  };

  const live =
    !!dashboard?.lastActivityAt && isFresh(dashboard.lastActivityAt, 30_000);

  return (
    <div className="min-h-screen">
      <div className="px-4 sm:px-6 md:px-10 py-6 md:py-10 max-w-6xl mx-auto">
        {/* Lightweight header — sidebar already shows the brand, so we just
            surface the live pulse + quick settings shortcut here. */}
        <div className="flex items-center justify-between gap-3 mb-2">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
            <span
              className={`size-1.5 rounded-full ${live ? "bg-emerald-500 animate-pulse" : "bg-zinc-400"}`}
              aria-hidden
            />
            {live ? "Live" : "Idle"}
            {dashboard && dashboard.slackChannels.length > 0 && (
              <span className="normal-case tracking-normal">
                · watching {dashboard.slackChannels.length} channel
                {dashboard.slackChannels.length === 1 ? "" : "s"}
              </span>
            )}
          </div>
          <SettingsMenu />
        </div>
        {/* Hero greeting + ask */}
        <section className="mt-2 sm:mt-4">
          <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight">
            What do you want to know?
          </h1>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            Ask in plain English. Answers are grounded in your documents and
            Slack messages.
          </p>

          <div className="mt-5">
            <AskBox
              value={question}
              onChange={setQuestion}
              onSubmit={() => ask(question)}
              onKeyDown={onKeyDown}
              asking={asking}
              inputRef={inputRef}
            />
            {!answer && !asking && (
              <div className="mt-3 flex flex-wrap gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => {
                      setQuestion(s);
                      ask(s);
                    }}
                    className="rounded-full border bg-[var(--card)] px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] hover:border-[var(--accent)]/40 transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>

        {/* Answer area */}
        {(asking || answer) && (
          <section className="mt-7">
            <AnswerCard asking={asking} answer={answer} />
          </section>
        )}

        {/* Dashboard grid */}
        <section className="mt-10 grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
          <div className="space-y-4">
            <ActivityCard dashboard={dashboard} channelNames={channelNames} />
          </div>
          <aside className="space-y-4">
            <StatsCard dashboard={dashboard} channelNames={channelNames} />
            <QuickActionsCard />
          </aside>
        </section>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Settings flyout
// ────────────────────────────────────────────────────────────────────────────

function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [resyncing, setResyncing] = useState(false);
  const [resyncResult, setResyncResult] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onClick = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!t.closest("[data-settings-menu]")) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  return (
    <>
      <div className="relative" data-settings-menu>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label="Settings"
          className="grid size-9 place-items-center rounded-md hover:bg-[var(--muted)] transition-colors"
        >
          <SettingsIcon />
        </button>
        {open && (
          <div className="absolute right-0 mt-1 w-64 rounded-lg border bg-[var(--card)] shadow-lg overflow-hidden">
            <MenuLink href="/ingest" label="Add sources" hint="Documents, PDFs, links" />
            <MenuLink href="/slack" label="Slack" hint="Channels & integration" />
            <MenuLink href="/graph" label="Knowledge map" hint="Entities & relationships" />
            <button
              type="button"
              disabled={resyncing}
              onClick={async () => {
                setResyncing(true);
                setResyncResult(null);
                try {
                  const r = await fetch("/api/slack/resync?limit=50", { method: "POST" });
                  const j = await r.json();
                  const enqueued = (j.channels || []).reduce(
                    (n: number, c: { enqueued?: number }) => n + (c.enqueued || 0),
                    0,
                  );
                  setResyncResult(`Pulled ${enqueued} messages — processing…`);
                } catch {
                  setResyncResult("Resync failed");
                } finally {
                  setResyncing(false);
                  setTimeout(() => setResyncResult(null), 6000);
                }
              }}
              className="block w-full px-3.5 py-2.5 text-left hover:bg-[var(--muted)]/60 transition-colors disabled:opacity-50"
            >
              <div className="text-sm font-medium">
                {resyncing ? "Re-syncing…" : "Re-sync Slack history"}
              </div>
              <div className="text-[11px] text-[var(--muted-foreground)]">
                {resyncResult || "Pull the last 50 messages per channel"}
              </div>
            </button>
            <div className="my-1 border-t border-[var(--border)]" />
            <MenuLink href="/skills" label="Export for agents" hint="SKILLS.md briefs" />
            <MenuLink href="/code" label="Codebase" hint="Repo intelligence" />
            <MenuLink href="/metrics" label="Infrastructure" hint="GPU / models" />
            <MenuLink href="/failures" label="Loop traps" hint="Agent debugging" />
            <div className="my-1 border-t border-[var(--border)]" />
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                setResetOpen(true);
              }}
              className="block w-full px-3.5 py-2.5 text-left hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
            >
              <div className="text-sm font-medium text-red-600 dark:text-red-400">
                Reset brain
              </div>
              <div className="text-[11px] text-[var(--muted-foreground)]">
                Clear all learned knowledge
              </div>
            </button>
          </div>
        )}
      </div>
      <ResetBrainModal open={resetOpen} onClose={() => setResetOpen(false)} />
    </>
  );
}

function MenuLink({
  href,
  label,
  hint,
}: {
  href: string;
  label: string;
  hint?: string;
}) {
  return (
    <Link
      href={href}
      className="block px-3.5 py-2.5 hover:bg-[var(--muted)]/60 transition-colors"
    >
      <div className="text-sm font-medium">{label}</div>
      {hint && (
        <div className="text-[11px] text-[var(--muted-foreground)]">{hint}</div>
      )}
    </Link>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Ask box + answer
// ────────────────────────────────────────────────────────────────────────────

function AskBox({
  value,
  onChange,
  onSubmit,
  onKeyDown,
  asking,
  inputRef,
}: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  asking: boolean;
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="rounded-2xl border bg-[var(--card)] p-2 shadow-sm focus-within:border-[var(--accent)]/60 focus-within:shadow-md transition-shadow"
    >
      <div className="flex items-end gap-2">
        <textarea
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          placeholder="Ask anything about your team's knowledge…"
          className="flex-1 resize-none bg-transparent px-3 py-2.5 text-base placeholder:text-[var(--muted-foreground)] focus:outline-none min-h-[44px] max-h-48"
          autoFocus
        />
        <button
          type="submit"
          disabled={asking || !value.trim()}
          className="inline-flex items-center gap-1.5 rounded-xl bg-[var(--foreground)] px-4 py-2 text-sm font-medium text-[var(--background)] hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {asking ? "Thinking…" : "Ask"}
        </button>
      </div>
    </form>
  );
}

function AnswerCard({
  asking,
  answer,
}: {
  asking: boolean;
  answer: AskResponse | null;
}) {
  if (asking) {
    return (
      <div className="rounded-2xl border bg-[var(--card)] p-6">
        <div className="flex items-center gap-2 text-[var(--muted-foreground)]">
          <span className="size-1.5 rounded-full bg-[var(--accent)] animate-pulse" />
          <span className="text-sm">Searching your knowledge…</span>
        </div>
        <div className="mt-4 space-y-2">
          <div className="h-4 w-3/4 rounded bg-[var(--muted)] animate-pulse" />
          <div className="h-4 w-2/3 rounded bg-[var(--muted)] animate-pulse" />
          <div className="h-4 w-1/2 rounded bg-[var(--muted)] animate-pulse" />
        </div>
      </div>
    );
  }
  if (!answer) return null;

  if (answer.error || answer.detail) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50/60 p-5 dark:border-red-900/50 dark:bg-red-950/20">
        <div className="text-sm font-semibold text-red-700 dark:text-red-300">
          Something went wrong
        </div>
        <p className="mt-1 text-sm text-red-700/80 dark:text-red-300/80">
          {answer.error || answer.detail}
        </p>
      </div>
    );
  }

  const text = answer.answer || answer.draft_answer || "";
  const conf = answer.feedback?.confidence;
  const grounded = answer.feedback?.grounded;
  const retrieved = answer.retrieved_texts || [];

  return (
    <div className="rounded-2xl border bg-[var(--card)] p-6 shadow-sm">
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
        Answer
        {typeof conf === "number" && (
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold normal-case tracking-normal ${
              grounded
                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                : "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
            }`}
          >
            {grounded ? "Grounded" : "Low confidence"} · {Math.round(conf * 100)}%
          </span>
        )}
        {answer.latency_ms !== undefined && (
          <span className="text-[10px] text-[var(--muted-foreground)] normal-case tracking-normal">
            {Math.round(answer.latency_ms)} ms
          </span>
        )}
      </div>
      <p className="mt-2 text-base leading-relaxed whitespace-pre-wrap">{text}</p>

      {retrieved.length > 0 && (
        <details className="mt-5">
          <summary className="cursor-pointer text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
            {retrieved.length} source{retrieved.length === 1 ? "" : "s"} used
          </summary>
          <ul className="mt-3 space-y-2.5">
            {retrieved.slice(0, 6).map((t, i) => (
              <li
                key={i}
                className="rounded-md border bg-[var(--background)]/40 px-3 py-2 text-[12px] leading-relaxed text-[var(--muted-foreground)] line-clamp-3"
              >
                {t}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Dashboard cards
// ────────────────────────────────────────────────────────────────────────────

function ActivityCard({
  dashboard,
  channelNames,
}: {
  dashboard: DashboardState | null;
  channelNames: Record<string, string>;
}) {
  const activity = dashboard?.activity || [];
  return (
    <div className="rounded-2xl border bg-[var(--card)] p-5">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Live activity</h2>
        <span className="text-[11px] text-[var(--muted-foreground)]">
          Refreshes every 5s
        </span>
      </div>
      {!dashboard ? (
        <p className="mt-4 text-sm text-[var(--muted-foreground)]">Loading…</p>
      ) : activity.length === 0 ? (
        <p className="mt-4 text-sm text-[var(--muted-foreground)]">
          Nothing yet. Add a source or send a Slack message — it&apos;ll show up
          here within seconds.
        </p>
      ) : (
        <ul className="mt-4 divide-y divide-[var(--border)]">
          {activity.map((a) => (
            <ActivityRow key={a.id} item={a} channelNames={channelNames} />
          ))}
        </ul>
      )}
    </div>
  );
}

function ActivityRow({
  item,
  channelNames,
}: {
  item: ActivityItem;
  channelNames: Record<string, string>;
}) {
  const fresh = isFresh(item.capturedAt, 30_000);
  const displayChannel =
    item.channelId && channelNames[item.channelId]
      ? `#${channelNames[item.channelId]}`
      : item.channelId
        ? `#${item.channelId}`
        : null;
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-md ${
            item.kind === "slack"
              ? "bg-[#4A154B] text-white"
              : item.kind === "doc"
                ? "bg-blue-100 text-blue-800 dark:bg-blue-950/40 dark:text-blue-200"
                : "bg-[var(--muted)] text-[var(--muted-foreground)]"
          }`}
          aria-hidden
        >
          {item.kind === "slack" ? <SlackIcon /> : <DocIcon />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
            <span className="font-medium">
              {item.kind === "slack"
                ? "Slack message"
                : item.kind === "doc"
                  ? "Document"
                  : "Source"}
            </span>
            {item.kind === "slack" && displayChannel && (
              <>
                <span aria-hidden>·</span>
                <span>{displayChannel}</span>
              </>
            )}
            {item.kind === "doc" && item.subtitle && (
              <>
                <span aria-hidden>·</span>
                <span>{item.subtitle}</span>
              </>
            )}
            <span aria-hidden>·</span>
            <span>{formatRelative(item.capturedAt)}</span>
            {fresh && (
              <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
                new
              </span>
            )}
          </div>
          <div className="mt-1 text-sm leading-snug">
            {item.text ? item.text : item.title}
          </div>
        </div>
      </div>
    </li>
  );
}

function StatsCard({
  dashboard,
  channelNames,
}: {
  dashboard: DashboardState | null;
  channelNames: Record<string, string>;
}) {
  const channelHint = (() => {
    if (!dashboard) return undefined;
    if (dashboard.slackChannels.length === 0) return undefined;
    const names = dashboard.slackChannels.map(
      (id) => (channelNames[id] ? `#${channelNames[id]}` : `#${id}`),
    );
    if (names.length <= 2) return names.join(", ");
    return `${names.slice(0, 2).join(", ")} +${names.length - 2}`;
  })();
  return (
    <div className="rounded-2xl border bg-[var(--card)] p-5">
      <h2 className="font-semibold">Your brain</h2>
      <dl className="mt-3 space-y-3 text-sm">
        <Stat dashboard={dashboard} label="Documents" valueKey="docs" />
        <Stat
          dashboard={dashboard}
          label="Slack messages"
          valueKey="slackMessages"
          hint={channelHint}
        />
        <Stat dashboard={dashboard} label="Facts extracted" valueKey="units" />
        <Stat dashboard={dashboard} label="Decisions" valueKey="decisions" />
      </dl>
    </div>
  );
}

function Stat({
  dashboard,
  label,
  valueKey,
  hint,
}: {
  dashboard: DashboardState | null;
  label: string;
  valueKey: keyof Pick<
    DashboardState,
    "docs" | "slackMessages" | "units" | "decisions"
  >;
  hint?: string;
}) {
  const value = dashboard ? dashboard[valueKey] : "—";
  return (
    <div className="flex items-baseline justify-between">
      <div>
        <dt className="text-[var(--muted-foreground)]">{label}</dt>
        {hint && (
          <div className="text-[11px] text-[var(--muted-foreground)]/80">{hint}</div>
        )}
      </div>
      <dd className="font-mono text-base font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function QuickActionsCard() {
  return (
    <div className="rounded-2xl border bg-[var(--card)] p-5">
      <h2 className="font-semibold">Quick actions</h2>
      <div className="mt-3 space-y-2">
        <ActionRow
          href="/ingest"
          label="Add documents"
          hint="PDFs, runbooks, notes"
        />
        <ActionRow
          href="/slack"
          label="Manage Slack"
          hint="Channels, mappings"
        />
        <ActionRow
          href="/welcome"
          label="Re-run onboarding"
          hint="Walk through setup again"
        />
      </div>
    </div>
  );
}

function ActionRow({
  href,
  label,
  hint,
}: {
  href: string;
  label: string;
  hint?: string;
}) {
  return (
    <Link
      href={href}
      className="flex items-center justify-between gap-3 rounded-lg border bg-[var(--background)]/40 px-3.5 py-2.5 hover:border-[var(--accent)]/40 transition-colors"
    >
      <div className="min-w-0">
        <div className="text-sm font-medium">{label}</div>
        {hint && (
          <div className="text-[11px] text-[var(--muted-foreground)]">{hint}</div>
        )}
      </div>
      <span className="text-[var(--muted-foreground)]">→</span>
    </Link>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────────────────────

function extractSlackText(content: string): string {
  // The realtime poller writes a fixed-shape body. Use the "after the last
  // blank line, after the USER_ID [ts] header" rule to fish out the message.
  const blocks = content.split("\n\n");
  if (blocks.length >= 3) {
    const last = blocks[blocks.length - 1];
    const nl = last.indexOf("\n");
    const text = nl >= 0 ? last.slice(nl + 1) : last;
    const trimmed = text.trim();
    // Reject if it still looks like raw JSON (search/thread MCP output).
    if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return trimmed;
  }
  // Fallback for sources that aren't the realtime shape — strip the leading
  // header lines and any JSON wrapper, return a short readable snippet.
  const cleaned = content.replace(/^\s*\{[^}]*?"(messages|results)":\s*"/, "").slice(0, 240);
  return cleaned.trim() || content.slice(0, 240);
}

function isFresh(iso: string, ms: number): boolean {
  if (!iso) return false;
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return false;
  return Date.now() - t < ms;
}

function formatRelative(iso: string): string {
  if (!iso) return "";
  const ms = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "just now";
  const s = Math.round(ms / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return new Date(iso).toLocaleDateString();
}

// ────────────────────────────────────────────────────────────────────────────
// Icons
// ────────────────────────────────────────────────────────────────────────────

function SettingsIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h0a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v0a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function SlackIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <path d="M5 15a2 2 0 1 1-2-2h2v2zm1 0a2 2 0 1 1 4 0v5a2 2 0 1 1-4 0v-5z" />
      <path d="M9 5a2 2 0 1 1 2-2v2H9zm0 1a2 2 0 1 1 0 4H4a2 2 0 1 1 0-4h5z" />
      <path d="M19 9a2 2 0 1 1 2 2h-2V9zm-1 0a2 2 0 1 1-4 0V4a2 2 0 1 1 4 0v5z" />
      <path d="M15 19a2 2 0 1 1-2 2v-2h2zm0-1a2 2 0 1 1 0-4h5a2 2 0 1 1 0 4h-5z" />
    </svg>
  );
}

function DocIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}
