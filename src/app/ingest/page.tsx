"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { ModelPicker } from "@/components/model-picker";

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
  addedRelationships?: number;
  supersededUnits?: number;
  charsExtracted?: number;
  vlmDescriptionChars?: number;
  totals: { sources: number; entities: number; units: number; relationships?: number };
};

type Tab = "text" | "file" | "image";

export default function IngestPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("text");

  // Text form state
  const [kind, setKind] = useState<KindValue>("slack");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [url, setUrl] = useState("");

  // File form state
  const [fileKind, setFileKind] = useState<KindValue>("doc");
  const [fileTitle, setFileTitle] = useState("");
  const [fileUrl, setFileUrl] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Image form state
  const [imgKind, setImgKind] = useState<KindValue>("doc");
  const [imgTitle, setImgTitle] = useState("");
  const [imgUrl, setImgUrl] = useState("");
  const [imgFile, setImgFile] = useState<File | null>(null);
  const [imgPreview, setImgPreview] = useState<string | null>(null);
  const imgInputRef = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);

  // Optional per-request model overrides. Empty string = "Auto".
  const [textModel, setTextModel] = useState("");        // text + file extraction
  const [vlmModel, setVlmModel] = useState("");          // image → description
  const [imgTextModel, setImgTextModel] = useState("");  // post-VLM extraction

  function onImgChange(e: React.ChangeEvent<HTMLInputElement>) {
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

  async function submitFile(e: React.FormEvent) {
    e.preventDefault();
    if (!uploadFile) return;
    setErr(null);
    setResult(null);
    setLoading(true);
    try {
      const fd = new FormData();
      fd.append("file", uploadFile, uploadFile.name);
      fd.append("title", fileTitle);
      fd.append("kind", fileKind);
      if (fileUrl) fd.append("url", fileUrl);
      if (textModel) fd.append("model", textModel);

      const res = await fetch("/api/ingest-file", { method: "POST", body: fd });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setResult(j);
      setFileTitle("");
      setUploadFile(null);
      setFileUrl("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      router.refresh();
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
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
        body: JSON.stringify({
          kind, title, content,
          url: url || undefined,
          model: textModel || undefined,
        }),
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
      if (vlmModel) fd.append("model", vlmModel);
      if (imgTextModel) fd.append("text_model", imgTextModel);

      const res = await fetch("/api/ingest-image", { method: "POST", body: fd });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setResult(j);
      setImgTitle("");
      setImgFile(null);
      setImgPreview(null);
      setImgUrl("");
      if (imgInputRef.current) imgInputRef.current.value = "";
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
        Paste text, upload a file, or drop an image. The brain extracts atomic facts,
        processes, decisions, owners, policies, and gotchas — then reconciles them
        against existing knowledge in ChromaDB.
      </p>

      {/* Tab switcher */}
      <div className="mt-6 flex gap-1 rounded-lg border bg-[var(--muted)]/30 p-1 w-fit">
        {([
          { id: "text", label: "Text / Paste" },
          { id: "file", label: "File Upload" },
          { id: "image", label: "Image / VLM" },
        ] as { id: Tab; label: string }[]).map((t) => (
          <button
            key={t.id}
            onClick={() => { setTab(t.id); setErr(null); setResult(null); }}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              tab === t.id
                ? "bg-[var(--foreground)] text-[var(--background)]"
                : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
            }`}
          >
            {t.label}
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

          <ModelPicker
            value={textModel}
            onChange={setTextModel}
            mode="text"
            label="Extraction model (optional)"
            hint="overrides extraction agent"
          />

          <SubmitRow loading={loading} disabled={!title || !content} label="Extract knowledge" />
        </form>
      )}

      {/* ── File upload form ── */}
      {tab === "file" && (
        <form onSubmit={submitFile} className="mt-8 space-y-4">
          <div className="rounded-md border border-zinc-200 bg-zinc-50 dark:bg-zinc-900/30 dark:border-zinc-700 px-4 py-3 text-sm text-zinc-700 dark:text-zinc-300">
            Upload a <strong>PDF</strong>, <strong>.txt</strong>, <strong>.md</strong>, or <strong>.csv</strong> file.
            The 70B model on the AMD MI300X extracts knowledge units and reconciles them against what the brain already knows.
          </div>

          <div className="grid grid-cols-[160px_1fr] gap-3">
            <Field label="Source type">
              <select
                value={fileKind}
                onChange={(e) => setFileKind(e.target.value as KindValue)}
                className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
              >
                {KINDS.map((k) => (
                  <option key={k.value} value={k.value}>{k.label}</option>
                ))}
              </select>
            </Field>
            <Field label="Title">
              <input
                value={fileTitle}
                onChange={(e) => setFileTitle(e.target.value)}
                required
                placeholder="e.g. Engineering handbook Q2 2026"
                className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
              />
            </Field>
          </div>

          <Field label="Source URL (optional)">
            <input
              value={fileUrl}
              onChange={(e) => setFileUrl(e.target.value)}
              placeholder="https://…"
              className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm"
            />
          </Field>

          <Field label="File (PDF, TXT, MD, CSV)">
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt,.md,.csv,text/plain,text/markdown,text/csv,application/pdf"
              onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
              required
              className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-[var(--foreground)] file:text-[var(--background)] file:px-3 file:py-1 file:text-xs file:font-medium"
            />
          </Field>

          {uploadFile && (
            <div className="text-[11px] text-[var(--muted-foreground)]">
              {uploadFile.name} · {(uploadFile.size / 1024).toFixed(1)} KB
            </div>
          )}

          <ModelPicker
            value={textModel}
            onChange={setTextModel}
            mode="text"
            label="Extraction model (optional)"
            hint="overrides extraction agent"
          />

          <SubmitRow loading={loading} disabled={!fileTitle || !uploadFile} label="Extract knowledge" />
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
              ref={imgInputRef}
              type="file"
              accept="image/*"
              onChange={onImgChange}
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

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <ModelPicker
              value={vlmModel}
              onChange={setVlmModel}
              mode="vlm"
              label="Vision model (optional)"
              hint="image → description"
            />
            <ModelPicker
              value={imgTextModel}
              onChange={setImgTextModel}
              mode="text"
              label="Extraction model (optional)"
              hint="description → units"
            />
          </div>

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
            Extracted {result.addedUnits} knowledge units
            {result.addedEntities > 0 && `, ${result.addedEntities} entities`}
            {(result.addedRelationships ?? 0) > 0 && (
              <span className="text-emerald-700 dark:text-emerald-400">
                , {result.addedRelationships} graph edges
              </span>
            )}.
            {(result.supersededUnits ?? 0) > 0 && (
              <span className="ml-1 text-amber-700 dark:text-amber-400">
                · {result.supersededUnits} superseded.
              </span>
            )}
            {result.charsExtracted
              ? ` ${result.charsExtracted.toLocaleString()} chars from file.`
              : ""}
            {result.vlmDescriptionChars
              ? ` VLM → ${result.vlmDescriptionChars} chars description.`
              : ""}
          </div>
          <div className="text-xs text-[var(--muted-foreground)] mt-1.5 flex items-center gap-3">
            <span>
              Brain: {result.totals.units} units · {result.totals.entities} entities
              {(result.totals.relationships ?? 0) > 0 && ` · ${result.totals.relationships} relationships`}
              {" "}from {result.totals.sources} sources
            </span>
            <a className="underline" href="/graph">View graph →</a>
            <a className="underline" href="/">Dashboard →</a>
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
