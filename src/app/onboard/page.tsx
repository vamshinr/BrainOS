"use client";

import { useState } from "react";

const DEPARTMENTS = [
  { value: "general", label: "Whole company" },
  { value: "engineering", label: "Engineering" },
  { value: "product", label: "Product" },
  { value: "legal", label: "Legal" },
  { value: "finance", label: "Finance" },
  { value: "hr", label: "HR" },
  { value: "sales", label: "Sales" },
  { value: "marketing", label: "Marketing" },
  { value: "operations", label: "Operations" },
  { value: "security", label: "Security" },
] as const;

const ROLE_SUGGESTIONS = [
  "Software Engineer",
  "Engineering Manager",
  "Product Manager",
  "Designer",
  "Data Scientist",
  "Account Executive",
  "Customer Success Manager",
  "Security Engineer",
];

type OnboardResponse = {
  doc: string;
  department: string;
  role: string;
  unit_count: number;
  sections: Record<string, number>;
  error?: string;
};

function MarkdownDoc({ text }: { text: string }) {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];
  let key = 0;

  for (const line of lines) {
    const k = key++;
    if (line.startsWith("# ")) {
      elements.push(
        <h1 key={k} className="text-2xl font-bold mt-6 mb-3 first:mt-0">
          {line.slice(2)}
        </h1>
      );
    } else if (line.startsWith("## ")) {
      elements.push(
        <h2 key={k} className="text-base font-semibold mt-5 mb-2 text-[var(--foreground)]">
          {line.slice(3)}
        </h2>
      );
    } else if (line.startsWith("### ")) {
      elements.push(
        <h3 key={k} className="text-sm font-semibold mt-4 mb-1 text-[var(--foreground)]">
          {line.slice(4)}
        </h3>
      );
    } else if (/^[-*] /.test(line)) {
      elements.push(
        <li key={k} className="ml-4 text-sm leading-relaxed list-disc">
          {line.slice(2)}
        </li>
      );
    } else if (/^\d+\. /.test(line)) {
      const num = line.match(/^(\d+)\. /)?.[1] ?? "";
      elements.push(
        <li key={k} className="ml-4 text-sm leading-relaxed list-decimal">
          {line.slice(num.length + 2)}
        </li>
      );
    } else if (line.startsWith("---")) {
      elements.push(<hr key={k} className="my-4 border-[var(--border)]" />);
    } else if (line.trim() === "") {
      elements.push(<div key={k} className="h-2" />);
    } else {
      elements.push(
        <p key={k} className="text-sm leading-relaxed">
          {line}
        </p>
      );
    }
  }

  return <div className="space-y-0.5">{elements}</div>;
}

export default function OnboardPage() {
  const [department, setDepartment] = useState("general");
  const [role, setRole] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<OnboardResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function generate() {
    setErr(null);
    setLoading(true);
    setResult(null);
    try {
      const res = await fetch("/api/onboard", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ department, role }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.error ?? `HTTP ${res.status}`);
      setResult(j);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  }

  function copy() {
    if (!result?.doc) return;
    navigator.clipboard.writeText(result.doc).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  const deptLabel =
    DEPARTMENTS.find((d) => d.value === department)?.label ?? department;

  return (
    <div className="px-4 sm:px-6 md:px-10 py-6 md:py-10 max-w-3xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Onboarding co-pilot
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Day-one context, generated.</h1>
      <p className="mt-2 text-[var(--muted-foreground)]">
        BrainOS reads everything it knows about a team and writes a personalized onboarding
        guide — processes, ownership, gotchas, policies, and a first-week checklist.
      </p>

      <div className="mt-8 rounded-xl border bg-[var(--card)] p-6 space-y-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
              Team / Department
            </label>
            <select
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              className="w-full rounded-md border bg-[var(--background)] px-3 py-2 text-sm"
            >
              {DEPARTMENTS.map((d) => (
                <option key={d.value} value={d.value}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1.5">
              Role (optional)
            </label>
            <input
              type="text"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="e.g. Software Engineer"
              className="w-full rounded-md border bg-[var(--background)] px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div>
          <div className="text-[10px] text-[var(--muted-foreground)] mb-1.5">Quick-fill role</div>
          <div className="flex flex-wrap gap-1.5">
            {ROLE_SUGGESTIONS.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRole(r)}
                className={`text-xs rounded-full border px-3 py-1 transition-colors ${
                  role === r
                    ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--accent)]"
                    : "bg-[var(--background)] hover:border-[var(--accent)]/40"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={generate}
          disabled={loading}
          className="w-full rounded-md bg-[var(--foreground)] text-[var(--background)] py-2.5 text-sm font-medium disabled:opacity-50 transition-opacity"
        >
          {loading ? "Generating…" : `Generate onboarding guide for ${deptLabel}`}
        </button>
      </div>

      {err && (
        <div className="mt-6 rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 dark:border-red-800 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          {err}
        </div>
      )}

      {loading && (
        <div className="mt-10 space-y-3 animate-pulse">
          <div className="h-6 w-48 rounded bg-[var(--muted)]/40" />
          <div className="h-4 w-full rounded bg-[var(--muted)]/30" />
          <div className="h-4 w-5/6 rounded bg-[var(--muted)]/30" />
          <div className="h-4 w-4/6 rounded bg-[var(--muted)]/30" />
          <div className="h-4 w-full rounded bg-[var(--muted)]/20" />
          <div className="h-4 w-3/4 rounded bg-[var(--muted)]/20" />
        </div>
      )}

      {result && !loading && (
        <div className="mt-8">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="rounded bg-[var(--muted)]/40 px-2 py-0.5 text-[11px] font-mono">
                {result.unit_count} units
              </span>
              {Object.entries(result.sections).map(([kind, count]) =>
                count > 0 ? (
                  <span
                    key={kind}
                    className="rounded bg-[var(--muted)]/30 px-2 py-0.5 text-[10px] text-[var(--muted-foreground)]"
                  >
                    {count} {kind}
                  </span>
                ) : null
              )}
            </div>
            <button
              onClick={copy}
              className="text-xs rounded-md border bg-[var(--card)] px-3 py-1.5 hover:bg-[var(--background)] transition-colors shrink-0"
            >
              {copied ? "Copied!" : "Copy Markdown"}
            </button>
          </div>

          <div className="rounded-xl border bg-[var(--card)] px-6 py-6">
            <MarkdownDoc text={result.doc} />
          </div>

          <div className="mt-4 text-[11px] text-[var(--muted-foreground)]">
            Share this doc with{" "}
            <span className="font-medium">{result.role || "the new hire"}</span> joining{" "}
            <span className="font-medium">{deptLabel}</span>. Re-generate any time — the brain
            stays up to date as knowledge is ingested.
          </div>
        </div>
      )}
    </div>
  );
}
