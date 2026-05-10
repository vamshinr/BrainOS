"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

type Step = 1 | 2 | 3;

type StarterDoc = {
  id: string;
  title: string;
  status: "pending" | "uploading" | "done" | "error";
  units?: number;
  error?: string;
};

type SuggestedQuestion = {
  id: string;
  text: string;
  status: "pending" | "asking" | "answered" | "rated_good" | "rated_bad";
  answer?: string;
  grounded?: boolean;
  confidence?: number;
};

const SEED_QUESTIONS: SuggestedQuestion[] = [
  { id: "q1", text: "Who owns billing in this company?", status: "pending" },
  { id: "q2", text: "What's our policy on production deploys?", status: "pending" },
  { id: "q3", text: "What gotchas should a new engineer know?", status: "pending" },
];

const STORAGE_KEY = "brainos-onboarding-step";

export default function OnboardingPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [hydrated, setHydrated] = useState(false);

  // Step 1 state
  const [docs, setDocs] = useState<StarterDoc[]>([]);
  const [pasteTitle, setPasteTitle] = useState("");
  const [pasteContent, setPasteContent] = useState("");
  const [pasting, setPasting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Step 2 state
  const [questions, setQuestions] = useState<SuggestedQuestion[]>(SEED_QUESTIONS);

  // Step 3 state — Slack connector
  type SlackChannel = { id: string; name: string; is_private: boolean; is_member: boolean; num_members?: number };
  type SlackStatus = {
    connected: boolean;
    team: string | null;
    channels: string[];
    lookback_days: number;
    last_sync: { running: boolean; last_run_at: string | null; ingested: number; last_error: string | null };
  };
  const [slackToken, setSlackToken] = useState("");
  const [slackTeam, setSlackTeam] = useState<string | null>(null);
  const [slackChannels, setSlackChannels] = useState<SlackChannel[] | null>(null);
  const [slackPicked, setSlackPicked] = useState<Set<string>>(new Set());
  const [slackBusy, setSlackBusy] = useState<"connecting" | "fetching" | "syncing" | null>(null);
  const [slackError, setSlackError] = useState<string | null>(null);
  const [slackStatus, setSlackStatus] = useState<SlackStatus | null>(null);

  // Hydrate step + initial source count
  useEffect(() => {
    const saved = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
    if (saved === "2" || saved === "3") setStep(Number(saved) as Step);
    setHydrated(true);
    fetch("/api/state").then(async (r) => {
      if (!r.ok) return;
      const j = await r.json();
      const sourceCount = (j.sources ?? []).length;
      if (sourceCount > 0 && !saved) {
        // User already has data — start them at step 2
        setStep(2);
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (hydrated && typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, String(step));
    }
  }, [step, hydrated]);

  const completedDocs = docs.filter((d) => d.status === "done").length;
  const completedQuestions = questions.filter(
    (q) => q.status === "answered" || q.status === "rated_good" || q.status === "rated_bad",
  ).length;
  const ratedQuestions = questions.filter(
    (q) => q.status === "rated_good" || q.status === "rated_bad",
  ).length;

  // ── Step 1 actions ──────────────────────────────────────────────────────────
  async function uploadFile(file: File) {
    const id = crypto.randomUUID();
    setDocs((prev) => [...prev, { id, title: file.name, status: "uploading" }]);
    const fd = new FormData();
    fd.append("file", file, file.name);
    fd.append("title", file.name);
    fd.append("kind", "doc");
    try {
      const res = await fetch("/api/ingest-file", { method: "POST", body: fd });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setDocs((prev) =>
        prev.map((d) =>
          d.id === id ? { ...d, status: "done", units: j.addedUnits ?? 0 } : d,
        ),
      );
    } catch (e) {
      setDocs((prev) =>
        prev.map((d) =>
          d.id === id ? { ...d, status: "error", error: String(e instanceof Error ? e.message : e) } : d,
        ),
      );
    }
  }

  async function onFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const list = Array.from(e.target.files ?? []);
    for (const f of list) {
      uploadFile(f); // fire in parallel
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    const list = Array.from(e.dataTransfer.files ?? []);
    for (const f of list) {
      uploadFile(f);
    }
  }

  async function submitPaste(e: React.FormEvent) {
    e.preventDefault();
    if (!pasteTitle || !pasteContent) return;
    const id = crypto.randomUUID();
    setDocs((prev) => [...prev, { id, title: pasteTitle, status: "uploading" }]);
    setPasting(true);
    try {
      const res = await fetch("/api/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "doc", title: pasteTitle, content: pasteContent }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setDocs((prev) =>
        prev.map((d) =>
          d.id === id ? { ...d, status: "done", units: j.addedUnits ?? 0 } : d,
        ),
      );
      setPasteTitle("");
      setPasteContent("");
    } catch (e) {
      setDocs((prev) =>
        prev.map((d) =>
          d.id === id ? { ...d, status: "error", error: String(e instanceof Error ? e.message : e) } : d,
        ),
      );
    } finally {
      setPasting(false);
    }
  }

  // ── Step 2 actions ──────────────────────────────────────────────────────────
  async function askQuestion(qid: string) {
    const q = questions.find((x) => x.id === qid);
    if (!q) return;
    setQuestions((prev) =>
      prev.map((x) => (x.id === qid ? { ...x, status: "asking" } : x)),
    );
    try {
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q.text }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setQuestions((prev) =>
        prev.map((x) =>
          x.id === qid
            ? {
                ...x,
                status: "answered",
                answer: j.answer,
                grounded: j.feedback?.grounded ?? false,
                confidence: j.feedback?.confidence,
              }
            : x,
        ),
      );
    } catch (e) {
      setQuestions((prev) =>
        prev.map((x) =>
          x.id === qid
            ? { ...x, status: "answered", answer: `Error: ${String(e instanceof Error ? e.message : e)}` }
            : x,
        ),
      );
    }
  }

  function rateQuestion(qid: string, good: boolean) {
    setQuestions((prev) =>
      prev.map((x) => (x.id === qid ? { ...x, status: good ? "rated_good" : "rated_bad" } : x)),
    );
  }

  function editQuestion(qid: string, text: string) {
    setQuestions((prev) =>
      prev.map((x) => (x.id === qid ? { ...x, text, status: "pending", answer: undefined } : x)),
    );
  }

  // ── Step 3 actions ──────────────────────────────────────────────────────────
  async function refreshSlackStatus() {
    try {
      const r = await fetch("/api/slack/status");
      if (r.ok) {
        const j: SlackStatus = await r.json();
        setSlackStatus(j);
        if (j.connected) {
          setSlackTeam(j.team);
          setSlackPicked(new Set(j.channels));
        }
      }
    } catch {}
  }

  // Refresh slack status on mount + every 10s while on step 3
  useEffect(() => {
    refreshSlackStatus();
    if (step !== 3) return;
    const id = setInterval(refreshSlackStatus, 10_000);
    return () => clearInterval(id);
  }, [step]);

  async function connectSlack() {
    if (!slackToken.trim()) return;
    setSlackBusy("connecting");
    setSlackError(null);
    try {
      const r = await fetch("/api/slack/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: slackToken.trim() }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ?? j.error ?? `HTTP ${r.status}`);
      setSlackTeam(j.team ?? "Slack");
      setSlackToken("");
      await fetchSlackChannels();
    } catch (e) {
      setSlackError(String(e instanceof Error ? e.message : e));
    } finally {
      setSlackBusy(null);
    }
  }

  async function fetchSlackChannels() {
    setSlackBusy("fetching");
    setSlackError(null);
    try {
      const r = await fetch("/api/slack/channels");
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ?? j.error ?? `HTTP ${r.status}`);
      setSlackChannels(j.channels ?? []);
    } catch (e) {
      setSlackError(String(e instanceof Error ? e.message : e));
    } finally {
      setSlackBusy(null);
    }
  }

  function toggleChannel(id: string) {
    setSlackPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function syncSlack() {
    if (slackPicked.size === 0) return;
    setSlackBusy("syncing");
    setSlackError(null);
    try {
      // Save selection (lookback 7 days, matches onboarding choice)
      const selRes = await fetch("/api/slack/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_ids: Array.from(slackPicked), lookback_days: 7 }),
      });
      if (!selRes.ok) {
        const j = await selRes.json();
        throw new Error(j.detail ?? j.error ?? `HTTP ${selRes.status}`);
      }
      const r = await fetch("/api/slack/sync", { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail ?? j.error ?? `HTTP ${r.status}`);
      await refreshSlackStatus();
      router.refresh();
    } catch (e) {
      setSlackError(String(e instanceof Error ? e.message : e));
    } finally {
      setSlackBusy(null);
    }
  }

  async function disconnectSlack() {
    await fetch("/api/slack/disconnect", { method: "DELETE" });
    setSlackTeam(null);
    setSlackChannels(null);
    setSlackPicked(new Set());
    setSlackStatus(null);
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div className="px-10 py-10 max-w-4xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Onboarding
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">
        Get your brain to its first useful answer.
      </h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-2xl">
        Three steps: drop in some docs, see the brain answer real questions, then add
        a high-volume source like Slack. You can come back to this any time.
      </p>

      {/* Stepper */}
      <ol className="mt-8 grid grid-cols-3 gap-3">
        <Stepper n={1} label="Drop in 5 docs" current={step} done={completedDocs >= 5} />
        <Stepper n={2} label="Ask 3 questions" current={step} done={ratedQuestions >= 3} />
        <Stepper n={3} label="Connect Slack" current={step} done={(slackStatus?.last_sync?.ingested ?? 0) > 0} />
      </ol>

      <div className="mt-10">
        {step === 1 && (
          <Step1
            docs={docs}
            completed={completedDocs}
            onFiles={onFiles}
            onDrop={onDrop}
            fileInputRef={fileInputRef}
            pasteTitle={pasteTitle}
            setPasteTitle={setPasteTitle}
            pasteContent={pasteContent}
            setPasteContent={setPasteContent}
            pasting={pasting}
            submitPaste={submitPaste}
          />
        )}

        {step === 2 && (
          <Step2
            questions={questions}
            ratedCount={ratedQuestions}
            answeredCount={completedQuestions}
            ask={askQuestion}
            rate={rateQuestion}
            edit={editQuestion}
          />
        )}

        {step === 3 && (
          <Step3
            token={slackToken}
            setToken={setSlackToken}
            team={slackTeam}
            channels={slackChannels}
            picked={slackPicked}
            togglePicked={toggleChannel}
            busy={slackBusy}
            error={slackError}
            status={slackStatus}
            connect={connectSlack}
            refetchChannels={fetchSlackChannels}
            sync={syncSlack}
            disconnect={disconnectSlack}
          />
        )}
      </div>

      {/* Footer nav */}
      <div className="mt-10 flex items-center justify-between border-t border-[var(--border)] pt-6">
        <button
          onClick={() => setStep((s) => (s > 1 ? ((s - 1) as Step) : s))}
          disabled={step === 1}
          className="text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-30"
        >
          ← Back
        </button>
        <div className="text-[11px] text-[var(--muted-foreground)]">Step {step} of 3</div>
        {step < 3 ? (
          <button
            onClick={() => setStep((s) => ((s + 1) as Step))}
            disabled={(step === 1 && completedDocs === 0) || (step === 2 && completedQuestions === 0)}
            className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium disabled:opacity-30"
          >
            {step === 1 && completedDocs < 5 ? `Continue anyway (${completedDocs}/5)` : "Next →"}
          </button>
        ) : (
          <button
            onClick={() => {
              if (typeof window !== "undefined") localStorage.removeItem(STORAGE_KEY);
              router.push("/");
            }}
            className="rounded-md bg-[var(--accent)] text-white px-4 py-2 text-sm font-medium"
          >
            Open dashboard →
          </button>
        )}
      </div>
    </div>
  );
}

// ── Components ────────────────────────────────────────────────────────────────

function Stepper({ n, label, current, done }: { n: number; label: string; current: Step; done: boolean }) {
  const isCurrent = n === current;
  const isPast = n < current || done;
  return (
    <li
      className={`rounded-lg border px-4 py-3 ${
        isCurrent
          ? "border-[var(--accent)]/60 bg-[var(--accent)]/5"
          : isPast
          ? "border-emerald-300 bg-emerald-50/50 dark:bg-emerald-950/20 dark:border-emerald-800/50"
          : "bg-[var(--card)]"
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`grid place-items-center size-5 rounded-full text-[10px] font-semibold ${
            done
              ? "bg-emerald-600 text-white"
              : isCurrent
              ? "bg-[var(--accent)] text-white"
              : "bg-[var(--muted)] text-[var(--muted-foreground)]"
          }`}
        >
          {done ? "✓" : n}
        </span>
        <div className="text-sm font-medium">{label}</div>
      </div>
    </li>
  );
}

function Step1({
  docs,
  completed,
  onFiles,
  onDrop,
  fileInputRef,
  pasteTitle,
  setPasteTitle,
  pasteContent,
  setPasteContent,
  pasting,
  submitPaste,
}: {
  docs: StarterDoc[];
  completed: number;
  onFiles: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onDrop: (e: React.DragEvent<HTMLDivElement>) => void;
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  pasteTitle: string;
  setPasteTitle: (s: string) => void;
  pasteContent: string;
  setPasteContent: (s: string) => void;
  pasting: boolean;
  submitPaste: (e: React.FormEvent) => void;
}) {
  return (
    <section>
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="text-xl font-semibold">Drop in 5 high-signal docs</h2>
        <span className="text-sm text-[var(--muted-foreground)] font-mono">{completed} / 5</span>
      </div>
      <p className="text-sm text-[var(--muted-foreground)] mb-6 max-w-2xl">
        Pick the docs that explain how your company actually works — a runbook, an org
        chart, a recent project doc, an onboarding wiki page, a postmortem. Skip
        marketing pages and stale archives.
      </p>

      <div
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        className="rounded-lg border-2 border-dashed bg-[var(--muted)]/20 px-8 py-10 text-center"
      >
        <div className="text-sm font-medium">Drop files here</div>
        <div className="text-xs text-[var(--muted-foreground)] mt-1">
          PDF, DOC, DOCX, TXT, MD, CSV — multiple at once
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.doc,.docx,.txt,.md,.csv"
          onChange={onFiles}
          className="hidden"
          id="onb-file"
        />
        <label
          htmlFor="onb-file"
          className="mt-4 inline-block rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium cursor-pointer"
        >
          Choose files
        </label>
      </div>

      {docs.length > 0 && (
        <ul className="mt-6 space-y-2">
          {docs.map((d) => (
            <li
              key={d.id}
              className="flex items-center justify-between rounded-md border bg-[var(--card)] px-4 py-2.5 text-sm"
            >
              <span className="truncate flex-1">{d.title}</span>
              <span className="ml-3 shrink-0 text-xs">
                {d.status === "uploading" && (
                  <span className="text-[var(--muted-foreground)]">extracting on MI300X…</span>
                )}
                {d.status === "done" && (
                  <span className="text-emerald-700 dark:text-emerald-400">
                    ✓ {d.units ?? 0} units
                  </span>
                )}
                {d.status === "error" && (
                  <span className="text-red-600 dark:text-red-400" title={d.error}>
                    failed
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      <details className="mt-8">
        <summary className="text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] cursor-pointer">
          Don&apos;t have files handy? Paste text instead.
        </summary>
        <form onSubmit={submitPaste} className="mt-4 space-y-3">
          <input
            value={pasteTitle}
            onChange={(e) => setPasteTitle(e.target.value)}
            placeholder="Title — e.g. Eng on-call runbook"
            className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
          />
          <textarea
            value={pasteContent}
            onChange={(e) => setPasteContent(e.target.value)}
            rows={8}
            placeholder="Paste the doc content here…"
            className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm font-mono"
          />
          <button
            type="submit"
            disabled={pasting || !pasteTitle || !pasteContent}
            className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium disabled:opacity-40"
          >
            {pasting ? "Extracting…" : "Add as doc"}
          </button>
        </form>
      </details>
    </section>
  );
}

function Step2({
  questions,
  ratedCount,
  answeredCount,
  ask,
  rate,
  edit,
}: {
  questions: SuggestedQuestion[];
  ratedCount: number;
  answeredCount: number;
  ask: (id: string) => void;
  rate: (id: string, good: boolean) => void;
  edit: (id: string, text: string) => void;
}) {
  return (
    <section>
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="text-xl font-semibold">Ask 3 real questions</h2>
        <span className="text-sm text-[var(--muted-foreground)] font-mono">
          {ratedCount} / 3 rated · {answeredCount} answered
        </span>
      </div>
      <p className="text-sm text-[var(--muted-foreground)] mb-6 max-w-2xl">
        Edit each question to match your company. Hit Ask, then mark whether the answer
        is correct. Bad answers usually mean the relevant doc wasn&apos;t in step 1 — go back
        and add it.
      </p>

      <ul className="space-y-4">
        {questions.map((q) => (
          <li key={q.id} className="rounded-lg border bg-[var(--card)] px-5 py-4">
            <input
              value={q.text}
              onChange={(e) => edit(q.id, e.target.value)}
              className="w-full bg-transparent text-sm font-medium outline-none border-b border-transparent focus:border-[var(--border)] pb-1"
            />
            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={() => ask(q.id)}
                disabled={q.status === "asking" || !q.text.trim()}
                className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-3 py-1.5 text-xs font-medium disabled:opacity-40"
              >
                {q.status === "asking" ? "Retrieving…" : q.status === "answered" || q.status === "rated_good" || q.status === "rated_bad" ? "Re-ask" : "Ask"}
              </button>
              {q.grounded !== undefined && (
                <span
                  className={`text-[11px] rounded px-2 py-0.5 ${
                    q.grounded
                      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
                      : "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
                  }`}
                >
                  {q.grounded ? "Grounded" : "Ungrounded"}
                  {q.confidence !== undefined ? ` · ${q.confidence.toFixed(2)}` : ""}
                </span>
              )}
            </div>

            {q.answer && (
              <div className="mt-3 rounded-md bg-[var(--muted)]/30 px-3 py-2 text-sm whitespace-pre-wrap">
                {q.answer}
              </div>
            )}

            {q.answer && (
              <div className="mt-3 flex items-center gap-2">
                <span className="text-[11px] text-[var(--muted-foreground)]">Was this right?</span>
                <button
                  onClick={() => rate(q.id, true)}
                  className={`text-xs rounded-md px-2.5 py-1 border ${
                    q.status === "rated_good"
                      ? "bg-emerald-600 text-white border-emerald-600"
                      : "hover:border-emerald-400"
                  }`}
                >
                  ✓ Good
                </button>
                <button
                  onClick={() => rate(q.id, false)}
                  className={`text-xs rounded-md px-2.5 py-1 border ${
                    q.status === "rated_bad"
                      ? "bg-red-600 text-white border-red-600"
                      : "hover:border-red-400"
                  }`}
                >
                  ✗ Needs more docs
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

type SlackChannel = { id: string; name: string; is_private: boolean; is_member: boolean; num_members?: number };
type SlackStatus = {
  connected: boolean;
  team: string | null;
  channels: string[];
  lookback_days: number;
  last_sync: { running: boolean; last_run_at: string | null; ingested: number; last_error: string | null };
};

function Step3({
  token,
  setToken,
  team,
  channels,
  picked,
  togglePicked,
  busy,
  error,
  status,
  connect,
  refetchChannels,
  sync,
  disconnect,
}: {
  token: string;
  setToken: (s: string) => void;
  team: string | null;
  channels: SlackChannel[] | null;
  picked: Set<string>;
  togglePicked: (id: string) => void;
  busy: "connecting" | "fetching" | "syncing" | null;
  error: string | null;
  status: SlackStatus | null;
  connect: () => void;
  refetchChannels: () => void;
  sync: () => void;
  disconnect: () => void;
}) {
  const connected = !!team || !!status?.connected;

  return (
    <section>
      <div className="flex items-baseline justify-between mb-4">
        <h2 className="text-xl font-semibold">Connect your Slack workspace</h2>
        <span className="text-sm text-[var(--muted-foreground)]">poll every 5 min · last 7 days</span>
      </div>
      <p className="text-sm text-[var(--muted-foreground)] mb-6 max-w-2xl">
        Slack is where the truth actually lives. Paste your bot token, pick the channels
        the brain should watch, and threads will flow in continuously as structured
        knowledge units.
      </p>

      {!connected ? (
        <div className="rounded-lg border bg-[var(--card)] px-5 py-5 space-y-4">
          <div>
            <label className="block">
              <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
                Bot token
              </div>
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="xoxb-…"
                autoComplete="off"
                spellCheck={false}
                className="w-full rounded-md border bg-[var(--background)] px-3 py-2 text-sm font-mono"
              />
            </label>
            <p className="mt-2 text-[11px] text-[var(--muted-foreground)]">
              Required scopes: <code>channels:history</code>, <code>channels:read</code>,{" "}
              <code>groups:history</code>, <code>groups:read</code>, <code>users:read</code>.
              Stored server-side in <code>slack_config.json</code> with permissions 0600.
            </p>
          </div>
          <button
            onClick={connect}
            disabled={busy === "connecting" || !token.trim()}
            className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium disabled:opacity-40"
          >
            {busy === "connecting" ? "Validating…" : "Connect"}
          </button>
        </div>
      ) : (
        <div className="space-y-5">
          <div className="rounded-lg border bg-[var(--card)] px-5 py-4 flex items-center justify-between">
            <div>
              <div className="text-sm font-medium">Connected to {team ?? status?.team}</div>
              <div className="text-[11px] text-[var(--muted-foreground)] mt-0.5">
                {(status?.channels?.length ?? 0)} channel{(status?.channels?.length ?? 0) === 1 ? "" : "s"} watched ·
                {" "}lookback {status?.lookback_days ?? 7}d
                {status?.last_sync?.last_run_at && (
                  <> · last sync {new Date(status.last_sync.last_run_at).toLocaleTimeString()}</>
                )}
                {status?.last_sync?.running && <> · syncing now…</>}
              </div>
            </div>
            <button
              onClick={disconnect}
              className="text-xs text-[var(--muted-foreground)] hover:text-red-600 underline underline-offset-2"
            >
              Disconnect
            </button>
          </div>

          <div className="rounded-lg border bg-[var(--card)] px-5 py-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold">Channels</h3>
              <button
                onClick={refetchChannels}
                disabled={busy === "fetching"}
                className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              >
                {busy === "fetching" ? "Loading…" : "Refresh"}
              </button>
            </div>
            {channels === null && busy !== "fetching" && (
              <button
                onClick={refetchChannels}
                className="text-xs rounded-md border bg-[var(--background)] px-3 py-1.5"
              >
                Load channel list
              </button>
            )}
            {channels && channels.length === 0 && (
              <p className="text-xs text-[var(--muted-foreground)]">
                No channels found. The bot may not be in any channels yet — invite it to a channel and refresh.
              </p>
            )}
            {channels && channels.length > 0 && (
              <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1 max-h-72 overflow-y-auto">
                {channels.map((ch) => (
                  <li key={ch.id}>
                    <label className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-[var(--muted)]/30 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={picked.has(ch.id)}
                        onChange={() => togglePicked(ch.id)}
                        disabled={!ch.is_member}
                      />
                      <span className="text-sm font-mono">
                        {ch.is_private ? "🔒" : "#"}{ch.name}
                      </span>
                      {!ch.is_member && (
                        <span
                          className="text-[10px] text-amber-600 dark:text-amber-400"
                          title="Bot not in this channel — invite the bot first"
                        >
                          not joined
                        </span>
                      )}
                      {ch.num_members !== undefined && (
                        <span className="text-[10px] text-[var(--muted-foreground)] ml-auto">
                          {ch.num_members}
                        </span>
                      )}
                    </label>
                  </li>
                ))}
              </ul>
            )}

            <div className="mt-4 flex items-center gap-3">
              <button
                onClick={sync}
                disabled={busy === "syncing" || picked.size === 0}
                className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium disabled:opacity-40"
              >
                {busy === "syncing" ? "Syncing…" : `Sync ${picked.size} channel${picked.size === 1 ? "" : "s"}`}
              </button>
              <span className="text-[11px] text-[var(--muted-foreground)]">
                First sync pulls the last 7 days. After that, polled every 5 min.
              </span>
            </div>
          </div>

          {status?.last_sync?.ingested ? (
            <div className="rounded-md border border-emerald-300 bg-emerald-50 dark:bg-emerald-950/30 dark:border-emerald-800 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-300">
              Ingested {status.last_sync.ingested} thread{status.last_sync.ingested === 1 ? "" : "s"} on the last sync.
            </div>
          ) : null}
        </div>
      )}

      {error && (
        <div className="mt-5 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {error}
        </div>
      )}
      {status?.last_sync?.last_error && (
        <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
          Last sync issue: {status.last_sync.last_error}
        </div>
      )}
    </section>
  );
}
