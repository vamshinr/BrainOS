"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

type ResetMode = "soft" | "hard";

const CONFIRM_PHRASE = "reset";

/**
 * Destructive action: wipe the brain.
 *   - soft: clears ChromaDB + brain.json (sources, units, entities, chunks),
 *           Slack config and onboarding completion are preserved.
 *   - hard: above, plus clears the onboarding flag so the wizard shows again.
 *
 * Requires the user to type "reset" before the destructive button activates.
 */
export function ResetBrainModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<ResetMode>("soft");
  const [phrase, setPhrase] = useState("");
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setPhrase("");
      setError(null);
      setMode("soft");
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !working) onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, working, onClose]);

  if (!open) return null;

  const canConfirm = phrase.trim().toLowerCase() === CONFIRM_PHRASE && !working;

  const runReset = async () => {
    setWorking(true);
    setError(null);
    try {
      // 1. Wipe knowledge.
      const wipeRes = await fetch("/api/state?all=true", { method: "DELETE" });
      if (!wipeRes.ok) {
        const t = await wipeRes.text();
        throw new Error(`Wipe failed: ${t}`);
      }
      // 2. Re-seed from recent Slack history so the brain isn't empty. The
      // poller alone only picks up brand-new messages, so without this step
      // a soft reset leaves you with effectively nothing until someone posts
      // again. Don't block the user on it failing — print and continue.
      try {
        await fetch("/api/slack/resync?limit=50", { method: "POST" });
      } catch {}
      // 3. If hard reset, also forget onboarding so the wizard shows again.
      if (mode === "hard") {
        await fetch("/api/onboarding/reset", { method: "POST" }).catch(() => {});
      }
      onClose();
      if (mode === "hard") {
        router.replace("/welcome");
      } else {
        router.refresh();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setWorking(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[80] grid place-items-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reset-brain-title"
    >
      <div
        className="w-full max-w-md rounded-2xl border bg-[var(--card)] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-[var(--border)]">
          <h2
            id="reset-brain-title"
            className="text-base font-semibold flex items-center gap-2"
          >
            <span className="grid size-6 place-items-center rounded-full bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300">
              !
            </span>
            Reset brain
          </h2>
          <p className="mt-1 text-[12px] text-[var(--muted-foreground)] leading-relaxed">
            This permanently clears everything Brain OS has learned. Slack
            credentials are preserved so the poller keeps running.
          </p>
        </div>

        <div className="px-5 py-4 space-y-4">
          <fieldset className="space-y-2">
            <legend className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
              What to clear
            </legend>
            <ModeOption
              checked={mode === "soft"}
              onSelect={() => setMode("soft")}
              title="Knowledge only"
              body="Sources, extracted facts, entities, raw chunks, vector embeddings."
            />
            <ModeOption
              checked={mode === "hard"}
              onSelect={() => setMode("hard")}
              title="Knowledge + onboarding"
              body="Everything above, plus the onboarding completion flag — the wizard will show again."
            />
          </fieldset>

          <div className="space-y-1.5">
            <label
              htmlFor="reset-confirm"
              className="block text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]"
            >
              Type <span className="font-mono text-[var(--foreground)]">reset</span> to confirm
            </label>
            <input
              id="reset-confirm"
              value={phrase}
              onChange={(e) => setPhrase(e.target.value)}
              autoFocus
              autoComplete="off"
              spellCheck={false}
              className="w-full rounded-md border bg-transparent px-3 py-2 text-sm font-mono"
            />
          </div>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
              {error}
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-[var(--border)] flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={working}
            className="rounded-md px-3 py-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] disabled:opacity-40"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={runReset}
            disabled={!canConfirm}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {working ? "Resetting…" : mode === "hard" ? "Reset everything" : "Reset knowledge"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ModeOption({
  checked,
  onSelect,
  title,
  body,
}: {
  checked: boolean;
  onSelect: () => void;
  title: string;
  body: string;
}) {
  return (
    <label
      className={`flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors ${
        checked
          ? "border-[var(--accent)] bg-[var(--accent)]/5"
          : "border-[var(--border)] hover:bg-[var(--muted)]/40"
      }`}
    >
      <input
        type="radio"
        checked={checked}
        onChange={onSelect}
        className="mt-1.5 accent-[var(--accent)]"
      />
      <div className="min-w-0">
        <div className="text-sm font-medium">{title}</div>
        <div className="text-[12px] text-[var(--muted-foreground)] leading-relaxed">{body}</div>
      </div>
    </label>
  );
}
