"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type WizardStep = "welcome" | "docs" | "slack" | "done";

type UploadStatus = "uploading" | "processing" | "ready" | "error";

type UploadItem = {
  id: string;          // local id (filename + timestamp)
  filename: string;
  size: number;
  status: UploadStatus;
  jobId?: string;
  error?: string;
  startedAt: number;
};

type SlackSaveResult = {
  bot_user_id?: string;
  team_name?: string;
  channels?: string[];
  default_department?: string;
  backfill?: { channel_id: string; fetched?: number; error?: string }[];
};

type OnboardingState = {
  docsReady: boolean;
  slackReady: boolean;
  docsCount: number;
  slackChannels: string[];
  slackConfigured: boolean;
  completedAt: string | null;
  complete: boolean;
};

const STEP_ORDER: WizardStep[] = ["welcome", "docs", "slack", "done"];

export default function WelcomePage() {
  const router = useRouter();
  const [step, setStep] = useState<WizardStep>("welcome");
  const [state, setState] = useState<OnboardingState | null>(null);

  // If they've already onboarded, kick them straight to the dashboard.
  // If both readiness checks already pass but completion was never marked
  // (e.g. they had docs + Slack configured before this UI existed), skip
  // ahead to the celebratory "Done" step so they can finish in one click.
  useEffect(() => {
    let cancelled = false;
    fetch("/api/onboarding/state", { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        setState(d);
        if (d.complete) {
          router.replace("/");
          return;
        }
        if (d.docsReady && d.slackReady) {
          setStep("done");
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [router]);

  // Periodic state refresh while in the wizard so step badges reflect
  // server-side progress (e.g., uploads finishing in the background).
  useEffect(() => {
    if (step === "welcome") return;
    const id = setInterval(() => {
      fetch("/api/onboarding/state", { cache: "no-store" })
        .then((r) => r.json())
        .then((d) => setState(d))
        .catch(() => {});
    }, 3000);
    return () => clearInterval(id);
  }, [step]);

  const stepIndex = STEP_ORDER.indexOf(step);

  return (
    <div className="min-h-screen bg-gradient-to-b from-[var(--background)] to-[var(--muted)]/40">
      {/* Top brand bar */}
      <header className="px-6 py-5 flex items-center gap-3">
        <BrandMark />
        <div>
          <div className="font-semibold text-[15px] leading-none">Brain OS</div>
          <div className="text-[11px] text-[var(--muted-foreground)] mt-1">
            Memory for your team
          </div>
        </div>
      </header>

      {/* Step indicator (hidden on welcome) */}
      {step !== "welcome" && (
        <div className="px-6">
          <div className="mx-auto max-w-2xl">
            <StepIndicator
              steps={["Documents", "Slack", "Ready"]}
              current={stepIndex - 1}
              done={state}
            />
          </div>
        </div>
      )}

      {/* Card */}
      <main className="px-6 pb-16">
        <div className="mx-auto max-w-2xl mt-6 sm:mt-10">
          {step === "welcome" && <WelcomeStep onNext={() => setStep("docs")} />}
          {step === "docs" && (
            <DocsStep
              state={state}
              onBack={() => setStep("welcome")}
              onNext={() => setStep("slack")}
            />
          )}
          {step === "slack" && (
            <SlackStep
              state={state}
              onBack={() => setStep("docs")}
              onNext={() => setStep("done")}
            />
          )}
          {step === "done" && (
            <DoneStep
              state={state}
              onOpen={async () => {
                try {
                  await fetch("/api/onboarding/complete", { method: "POST" });
                } catch {}
                router.replace("/");
              }}
            />
          )}
        </div>
      </main>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Step 0 — Welcome
// ────────────────────────────────────────────────────────────────────────────

function WelcomeStep({ onNext }: { onNext: () => void }) {
  return (
    <section className="rounded-2xl border bg-[var(--card)] p-8 sm:p-12 shadow-sm">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
        Welcome
      </div>
      <h1 className="mt-3 text-3xl sm:text-4xl font-semibold tracking-tight">
        Your team's memory, finally in one place.
      </h1>
      <p className="mt-4 text-[var(--muted-foreground)] leading-relaxed max-w-xl">
        Brain OS turns the documents you trust and the conversations you have
        on Slack into reconciled, attributable facts your team and your agents
        can rely on. Two short steps, you&apos;ll be done in under three minutes.
      </p>

      <ul className="mt-8 space-y-3 text-sm">
        <BulletItem n={1} title="Upload your source-of-truth documents" body="PDFs, runbooks, policies, meeting notes. We extract atomic facts with evidence." />
        <BulletItem n={2} title="Connect a Slack channel" body="Past messages get ingested instantly; new ones every 5 seconds." />
      </ul>

      <div className="mt-10 flex justify-end">
        <PrimaryButton onClick={onNext}>Get started →</PrimaryButton>
      </div>
    </section>
  );
}

function BulletItem({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <li className="flex items-start gap-3">
      <span className="mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-[var(--accent)]/10 text-[var(--accent)] text-xs font-semibold">
        {n}
      </span>
      <div>
        <div className="font-medium">{title}</div>
        <div className="text-[var(--muted-foreground)]">{body}</div>
      </div>
    </li>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Step 1 — Documents
// ────────────────────────────────────────────────────────────────────────────

const MAX_FILE_BYTES = 25 * 1024 * 1024; // 25 MB per file
const ACCEPTED = ".pdf,.txt,.md,.csv,.doc,.docx";

function DocsStep({
  state,
  onBack,
  onNext,
}: {
  state: OnboardingState | null;
  onBack: () => void;
  onNext: () => void;
}) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const docsCount = state?.docsCount ?? 0;
  const localUploaded = items.filter((i) => i.status === "ready").length;
  const totalReady = Math.max(docsCount, localUploaded);
  const canContinue = totalReady > 0;

  const startUpload = useCallback(async (file: File) => {
    const id = `${file.name}-${Date.now()}`;
    const initial: UploadItem = {
      id,
      filename: file.name,
      size: file.size,
      status: "uploading",
      startedAt: Date.now(),
    };
    setItems((prev) => [initial, ...prev]);

    if (file.size > MAX_FILE_BYTES) {
      setItems((prev) =>
        prev.map((it) =>
          it.id === id ? { ...it, status: "error", error: "File exceeds 25 MB limit" } : it,
        ),
      );
      return;
    }

    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("kind", "doc");
      const res = await fetch("/api/ingest-file", { method: "POST", body: fd });
      if (!res.ok) {
        const errBody = await res.text();
        throw new Error(errBody || `HTTP ${res.status}`);
      }
      const body = await res.json();
      setItems((prev) =>
        prev.map((it) =>
          it.id === id
            ? { ...it, status: "processing", jobId: body.job_id }
            : it,
        ),
      );
    } catch (e) {
      setItems((prev) =>
        prev.map((it) =>
          it.id === id ? { ...it, status: "error", error: String(e) } : it,
        ),
      );
    }
  }, []);

  // Poll job status for everything currently processing.
  useEffect(() => {
    const processing = items.filter((i) => i.status === "processing" && i.jobId);
    if (processing.length === 0) return;
    const id = setInterval(async () => {
      const updates = await Promise.all(
        processing.map(async (it) => {
          try {
            const r = await fetch(`/api/jobs/${it.jobId}`, { cache: "no-store" });
            if (!r.ok) return null;
            const j = await r.json();
            return { id: it.id, status: j?.status };
          } catch {
            return null;
          }
        }),
      );
      setItems((prev) =>
        prev.map((it) => {
          const u = updates.find((u) => u && u.id === it.id);
          if (!u) return it;
          if (u.status === "succeeded" || u.status === "completed") {
            return { ...it, status: "ready" };
          }
          if (u.status === "failed" || u.status === "error") {
            return { ...it, status: "error", error: "Processing failed" };
          }
          return it;
        }),
      );
    }, 1500);
    return () => clearInterval(id);
  }, [items]);

  const onPick = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      Array.from(files).forEach(startUpload);
    },
    [startUpload],
  );

  return (
    <section className="rounded-2xl border bg-[var(--card)] p-7 sm:p-10 shadow-sm">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
        Step 1 of 2
      </div>
      <h2 className="mt-2 text-2xl sm:text-3xl font-semibold tracking-tight">
        Bring in your knowledge.
      </h2>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-xl leading-relaxed">
        Upload the documents your team treats as ground truth. PDFs, runbooks,
        meeting notes, policies — anything written down. We&apos;ll extract atomic
        facts, owners, and decisions with provenance.
      </p>

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          onPick(e.dataTransfer?.files ?? null);
        }}
        onClick={() => fileInputRef.current?.click()}
        className={`mt-7 cursor-pointer rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors ${
          dragOver
            ? "border-[var(--accent)] bg-[var(--accent)]/5"
            : "border-[var(--border)] hover:bg-[var(--muted)]/30"
        }`}
      >
        <div className="mx-auto grid size-12 place-items-center rounded-xl bg-[var(--accent)]/10 text-[var(--accent)]">
          <UploadIcon />
        </div>
        <div className="mt-4 text-base font-medium">Drop files here, or click to browse</div>
        <div className="mt-1 text-xs text-[var(--muted-foreground)]">
          PDF, DOC, DOCX, TXT, MD, CSV · up to 25 MB each
        </div>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept={ACCEPTED}
          className="hidden"
          onChange={(e) => {
            onPick(e.target.files);
            e.currentTarget.value = "";
          }}
        />
      </div>

      {/* Uploaded list */}
      {(items.length > 0 || docsCount > 0) && (
        <div className="mt-6">
          <div className="mb-2 text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
            {items.length === 0
              ? `${docsCount} document${docsCount === 1 ? "" : "s"} already ingested`
              : "Uploads"}
          </div>
          <ul className="space-y-2">
            {items.map((it) => (
              <UploadRow key={it.id} item={it} />
            ))}
          </ul>
          {items.length === 0 && docsCount > 0 && (
            <p className="text-sm text-[var(--muted-foreground)]">
              You already have {docsCount} document{docsCount === 1 ? "" : "s"} in your brain.
              Add more above, or continue.
            </p>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="mt-10 flex items-center justify-between gap-3">
        <SecondaryButton onClick={onBack}>← Back</SecondaryButton>
        <div className="flex items-center gap-2">
          {!canContinue && (
            <span className="text-xs text-[var(--muted-foreground)]">
              Add at least one document to continue
            </span>
          )}
          <PrimaryButton onClick={onNext} disabled={!canContinue}>
            Continue →
          </PrimaryButton>
        </div>
      </div>
    </section>
  );
}

function UploadRow({ item }: { item: UploadItem }) {
  const isWorking = item.status === "uploading" || item.status === "processing";
  return (
    <li className="flex items-center gap-3 rounded-lg border bg-[var(--background)]/40 px-3.5 py-2.5">
      <span className="grid size-7 shrink-0 place-items-center rounded-md bg-[var(--muted)] text-[var(--muted-foreground)]">
        <FileIcon />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{item.filename}</div>
        <div className="mt-0.5 text-[11px] text-[var(--muted-foreground)]">
          {(item.size / 1024 / 1024).toFixed(2)} MB
          {item.error && <span className="ml-2 text-red-600">· {item.error}</span>}
        </div>
      </div>
      <StatusPill status={item.status} pulse={isWorking} />
    </li>
  );
}

function StatusPill({ status, pulse }: { status: UploadStatus; pulse: boolean }) {
  const map = {
    uploading: { label: "Uploading…", tone: "bg-[var(--muted)] text-[var(--muted-foreground)]" },
    processing: { label: "Extracting…", tone: "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300" },
    ready: { label: "Ready", tone: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300" },
    error: { label: "Failed", tone: "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300" },
  }[status];
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ${map.tone}`}>
      {pulse && <span className="size-1.5 rounded-full bg-current opacity-60 animate-pulse" />}
      {map.label}
    </span>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Step 2 — Slack
// ────────────────────────────────────────────────────────────────────────────

function SlackStep({
  state,
  onBack,
  onNext,
}: {
  state: OnboardingState | null;
  onBack: () => void;
  onNext: () => void;
}) {
  const alreadyConnected = !!state?.slackReady;
  const [botToken, setBotToken] = useState("");
  const [channels, setChannels] = useState("");
  const [department, setDepartment] = useState("general");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SlackSaveResult | null>(null);

  const channelsList = useMemo(
    () =>
      channels
        .split(/[\s,]+/)
        .map((c) => c.trim())
        .filter(Boolean),
    [channels],
  );

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const res = await fetch("/api/onboarding/slack/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          bot_token: botToken.trim(),
          channels: channelsList,
          default_department: department.trim() || "general",
        }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.detail || body?.error || `HTTP ${res.status}`);
      setResult(body);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const connected = alreadyConnected || !!result;

  return (
    <section className="rounded-2xl border bg-[var(--card)] p-7 sm:p-10 shadow-sm">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
        Step 2 of 2
      </div>
      <h2 className="mt-2 text-2xl sm:text-3xl font-semibold tracking-tight">
        Connect Slack.
      </h2>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-xl leading-relaxed">
        Add the channels you want Brain OS to learn from. Past messages get
        backfilled right away; new ones flow in within 5 seconds.
      </p>

      {connected ? (
        <ConnectedState state={state} result={result} />
      ) : (
        <div className="mt-7 space-y-5">
          <Field
            label="Slack Bot Token"
            hint="Starts with xoxb- · From your Slack app → OAuth & Permissions → Bot User OAuth Token"
          >
            <input
              type="password"
              value={botToken}
              onChange={(e) => setBotToken(e.target.value)}
              placeholder="xoxb-…"
              autoComplete="off"
              className="w-full rounded-md border bg-transparent px-3.5 py-2.5 text-sm font-mono"
            />
          </Field>

          <Field
            label="Channel IDs"
            hint="Comma- or space-separated. In Slack: right-click a channel → View channel details → Channel ID at the bottom."
          >
            <input
              value={channels}
              onChange={(e) => setChannels(e.target.value)}
              placeholder="C0B2ALQLA4F, C0B2QPXK2F7"
              className="w-full rounded-md border bg-transparent px-3.5 py-2.5 text-sm font-mono"
            />
            {channelsList.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {channelsList.map((c) => (
                  <span
                    key={c}
                    className="rounded-full bg-[var(--muted)] px-2.5 py-0.5 text-[11px] font-mono"
                  >
                    {c}
                  </span>
                ))}
              </div>
            )}
          </Field>

          <Field label="Default department" hint="What team owns these channels by default?">
            <select
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              className="w-full rounded-md border bg-transparent px-3.5 py-2.5 text-sm"
            >
              {["general", "engineering", "product", "sales", "operations", "finance", "legal", "hr"].map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </Field>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3.5 py-2.5 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
              {error}
            </div>
          )}

          <PrimaryButton
            onClick={save}
            disabled={saving || !botToken.startsWith("xoxb-") || channelsList.length === 0}
            block
          >
            {saving ? "Connecting…" : "Connect Slack"}
          </PrimaryButton>
        </div>
      )}

      <div className="mt-10 flex items-center justify-between gap-3">
        <SecondaryButton onClick={onBack}>← Back</SecondaryButton>
        <PrimaryButton onClick={onNext} disabled={!connected}>
          Continue →
        </PrimaryButton>
      </div>
    </section>
  );
}

function ConnectedState({
  state,
  result,
}: {
  state: OnboardingState | null;
  result: SlackSaveResult | null;
}) {
  const channels = result?.channels || state?.slackChannels || [];
  return (
    <div className="mt-7 rounded-xl border border-emerald-200 bg-emerald-50/60 p-5 dark:border-emerald-900/50 dark:bg-emerald-950/20">
      <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-300">
        <CheckIcon />
        <span className="font-semibold">Slack connected</span>
      </div>
      <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
        {result?.team_name && (
          <KV label="Workspace" value={result.team_name} />
        )}
        {result?.bot_user_id && (
          <KV label="Bot user" value={result.bot_user_id} mono />
        )}
        <KV
          label="Channels"
          value={channels.length ? channels.join(", ") : "—"}
          mono
        />
        {result?.default_department && (
          <KV label="Department" value={result.default_department} />
        )}
      </div>
      {result?.backfill && result.backfill.length > 0 && (
        <div className="mt-4 text-xs text-[var(--muted-foreground)]">
          Backfilling{" "}
          {result.backfill
            .filter((b) => typeof b.fetched === "number")
            .map((b) => `${b.fetched} from ${b.channel_id}`)
            .join(", ") || "channel history"}
          {" · the brain will populate as messages are processed."}
        </div>
      )}
    </div>
  );
}

function KV({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
        {label}
      </div>
      <div className={`mt-0.5 ${mono ? "font-mono text-xs" : "text-sm"}`}>{value}</div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Step 3 — Done
// ────────────────────────────────────────────────────────────────────────────

function DoneStep({
  state,
  onOpen,
}: {
  state: OnboardingState | null;
  onOpen: () => void;
}) {
  return (
    <section className="rounded-2xl border bg-[var(--card)] p-8 sm:p-12 shadow-sm text-center">
      <div className="mx-auto grid size-14 place-items-center rounded-full bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
        <CheckIcon size={26} />
      </div>
      <h2 className="mt-5 text-2xl sm:text-3xl font-semibold tracking-tight">
        Your workspace is ready.
      </h2>
      <p className="mt-3 text-[var(--muted-foreground)] max-w-md mx-auto leading-relaxed">
        Brain OS is now learning from your documents and Slack channels. Ask
        anything about your company in plain English — you&apos;ll get answers
        grounded in real evidence.
      </p>

      <div className="mt-7 grid grid-cols-2 gap-3 max-w-sm mx-auto">
        <Stat label="Documents" value={state?.docsCount ?? 0} />
        <Stat label="Channels" value={state?.slackChannels?.length ?? 0} />
      </div>

      <div className="mt-10">
        <PrimaryButton onClick={onOpen} block>
          Open my workspace →
        </PrimaryButton>
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border bg-[var(--background)]/40 px-4 py-3 text-left">
      <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
        {label}
      </div>
      <div className="mt-0.5 text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Shared UI primitives
// ────────────────────────────────────────────────────────────────────────────

function StepIndicator({
  steps,
  current,
  done,
}: {
  steps: string[];
  current: number;
  done: OnboardingState | null;
}) {
  return (
    <ol className="flex items-center gap-2">
      {steps.map((s, i) => {
        const isComplete =
          (i === 0 && done?.docsReady) ||
          (i === 1 && done?.slackReady) ||
          (i === 2 && done?.complete) ||
          i < current;
        const isCurrent = i === current;
        return (
          <li key={s} className="flex-1">
            <div className="flex items-center gap-2">
              <span
                className={`inline-flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                  isComplete
                    ? "bg-emerald-500 text-white"
                    : isCurrent
                      ? "bg-[var(--accent)] text-white"
                      : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                }`}
                aria-hidden
              >
                {isComplete ? "✓" : i + 1}
              </span>
              <span
                className={`text-xs font-medium ${
                  isCurrent
                    ? "text-[var(--foreground)]"
                    : "text-[var(--muted-foreground)]"
                }`}
              >
                {s}
              </span>
              {i < steps.length - 1 && (
                <span className="ml-1 h-px flex-1 bg-[var(--border)]" />
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="block text-sm font-medium">{label}</span>
      {hint && (
        <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)] leading-relaxed">
          {hint}
        </span>
      )}
      <div className="mt-2">{children}</div>
    </label>
  );
}

function PrimaryButton({
  children,
  onClick,
  disabled,
  block,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  block?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center rounded-md bg-[var(--foreground)] px-4 py-2.5 text-sm font-medium text-[var(--background)] transition-opacity hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed ${
        block ? "w-full" : ""
      }`}
    >
      {children}
    </button>
  );
}

function SecondaryButton({
  children,
  onClick,
}: {
  children: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-md px-3 py-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
    >
      {children}
    </button>
  );
}

function BrandMark() {
  return (
    <div className="size-9 rounded-xl bg-[var(--accent)] grid place-items-center text-white shadow-sm">
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M9 3a4 4 0 0 0-4 4v1a3 3 0 0 0-2 2.83V14a3 3 0 0 0 2 2.83V18a4 4 0 0 0 4 4h0" />
        <path d="M15 3a4 4 0 0 1 4 4v1a3 3 0 0 1 2 2.83V14a3 3 0 0 1-2 2.83V18a4 4 0 0 1-4 4h0" />
        <line x1="9" y1="3" x2="15" y2="3" />
        <line x1="9" y1="22" x2="15" y2="22" />
      </svg>
    </div>
  );
}

function UploadIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
    </svg>
  );
}

function CheckIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}
