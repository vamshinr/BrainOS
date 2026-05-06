"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";

const KINDS = [
  { value: "slack", label: "Slack" },
  { value: "email", label: "Email" },
  { value: "ticket", label: "Support ticket" },
  { value: "doc", label: "Doc / runbook" },
  { value: "meeting", label: "Meeting notes" },
  { value: "wiki", label: "Wiki" },
  { value: "code", label: "Code / PR" },
  { value: "other", label: "Other" },
] as const;

type KindValue = (typeof KINDS)[number]["value"];

type Result = {
  sourceId: string;
  addedUnits: number;
  addedEntities: number;
  vlmDescriptionChars?: number;
  totals: { sources: number; entities: number; units: number };
};

type Tab = "text" | "image";

export default function IngestPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("text");

  // Text form state
  const [kind, setKind] = useState<KindValue>("slack");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [url, setUrl] = useState("");

  // Image form state
  const [imgKind, setImgKind] = useState<KindValue>("doc");
  const [imgTitle, setImgTitle] = useState("");
  const [imgUrl, setImgUrl] = useState("");
  const [imgFile, setImgFile] = useState<File | null>(null);
  const [imgPreview, setImgPreview] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setImgFile(f);
    if (f) {
      const reader = new FileReader();
      reader.onload = (ev) => setImgPreview(ev.target?.result as string);
      reader.readAsDataURL(f);
    } else {
      setImgPreview(null);
    }
  }

  async function submitText(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setResult(null);
    setLoading(true);
    try {
      const res = await fetch("/api/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, title, content, url: url || undefined }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setResult(j);
      setTitle("");
      setContent("");
      setUrl("");
      router.refresh();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }

  async function submitImage(e: React.FormEvent) {
    e.preventDefault();
    if (!imgFile) return;
    setErr(null);
    setResult(null);
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", imgFile, imgFile.name);
      fd.append("title", imgTitle);
      fd.append("kind", imgKind);
      if (imgUrl) fd.append("url", imgUrl);

      const res = await fetch("/api/ingest-image", { method: "POST", body: fd });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setResult(j);
      setImgTitle("");
      setImgFile(null);
      setImgPreview(null);
      setImgUrl("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      router.refresh();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="px-10 py-10 max-w-3xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Ingest
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">
        Drop in a knowledge source.
      </h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-xl">
        Paste text or upload an image — screenshots, diagrams, whiteboards, slides.
        The brain extracts atomic facts, processes, decisions, owners, policies,
        and gotchas, then stores them in ChromaDB for semantic retrieval.
      </p>

      {/* Tab switcher */}
      <div className="mt-6 flex gap-1 rounded-lg border bg-[var(--muted)]/30 p-1 w-fit">
        {(["text", "image"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => { setTab(t); setErr(null); setResult(null); }}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              tab === t
                ? "bg-[var(--foreground)] text-[var(--background)]"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            {t === "text" ? "Text / Paste" : "Image / Screenshot"}
          </button>
        ))}
      </div>

      {/* ── Text form ── */}
      {tab === "text" && (
        <form onSubmit={submitText} className="mt-8 space-y-4">
          <div className="grid grid-cols-[160px_1fr] gap-3">
            <Field label="Source type">
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as KindValue)}
                className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
              >
                {KINDS.map((k) => (
                  <option key={k.value} value={k.value}>{k.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Title">
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                placeholder="e.g. #eng-billing — Stripe migration kickoff"
                className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
              />
            </Field>
          </div>

          <Field label="Source URL (optional)">
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://…"
              className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
            />
          </Field>

          <Field label="Content">
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              required
              rows={14}
              placeholder="Paste the raw thread / email / ticket / doc here. Don't summarize — the 70B model works better on raw content."
              className="w-full rounded-md border bg-[var(--card)] px-3 py-3 text-sm font-mono leading-relaxed"
            />
          </Field>

          <SubmitRow loading={loading} disabled={!title || !content} label="Extract knowledge" />
        </form>
      )}

      {/* ── Image form ── */}
      {tab === "image" && (
        <form onSubmit={submitImage} className="mt-8 space-y-4">
          <div className="rounded-md border border-blue-200 bg-blue-50 dark:bg-blue-950/20 dark:border-blue-800 px-4 py-3 text-sm text-blue-800 dark:text-blue-300">
            <span className="font-medium">VLM pipeline</span> — Upload a screenshot, architecture diagram,
            whiteboard photo, or slide. The vision model describes it, then the 70B model extracts
            knowledge units. Both run on the AMD MI300X.
          </div>

          <div className="grid grid-cols-[160px_1fr] gap-3">
            <Field label="Source type">
              <select
                value={imgKind}
                onChange={(e) => setImgKind(e.target.value as KindValue)}
                className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
              >
                {KINDS.map((k) => (
                  <option key={k.value} value={k.value}>{k.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Title">
              <input
                value={imgTitle}
                onChange={(e) => setImgTitle(e.target.value)}
                required
                placeholder="e.g. System architecture diagram Q2 2026"
                className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
              />
            </Field>
          </div>

          <Field label="Source URL (optional)">
            <input
              value={imgUrl}
              onChange={(e) => setImgUrl(e.target.value)}
              placeholder="https://…"
              className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
            />
          </Field>

          <Field label="Image file">
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={onFileChange}
              required
              className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-[var(--foreground)] file:text-[var(--background)] file:px-3 file:py-1 file:text-xs file:font-medium"
            />
          </Field>

          {imgPreview && (
            <div className="rounded-md border overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={imgPreview}
                alt="Preview"
                className="max-h-64 w-full object-contain bg-[var(--muted)]/20"
              />
            </div>
          )}

          <SubmitRow loading={loading} disabled={!imgTitle || !imgFile} label="Ingest via VLM" />
        </form>
      )}

      {err && (
        <div className="mt-6 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {err}
        </div>
      )}

      {result && (
        <div className="mt-6 rounded-md border border-emerald-300 bg-emerald-50 dark:bg-emerald-950/30 dark:border-emerald-800 px-4 py-3 text-sm">
          <div className="font-medium">
            Extracted {result.addedUnits} knowledge units and {result.addedEntities} entities.
            {result.vlmDescriptionChars
              ? ` VLM generated ${result.vlmDescriptionChars} chars of description.`
              : ""}
          </div>
          <div className="text-xs text-[var(--muted-foreground)] mt-1">
            Brain now contains {result.totals.units} units across {result.totals.entities} entities
            from {result.totals.sources} sources.{" "}
            <a className="underline" href="/">View dashboard →</a>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
        {label}
      </div>
      {children}
    </label>
  );
}

function SubmitRow({
  loading,
  disabled,
  label,
}: {
  loading: boolean;
  disabled: boolean;
  label: string;
}) {
  return (
    <div className="flex items-center gap-3 pt-2">
      <button
        type="submit"
        disabled={loading || disabled}
        className="rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium disabled:opacity-50"
      >
        {loading ? "Processing on AMD MI300X…" : label}
      </button>
      {loading && (
        <span className="text-xs text-[var(--muted-foreground)]">
          Calling 70B model, embedding into ChromaDB…
        </span>
      )}
    </div>
  );
}
