"use client";

import { useState } from "react";
import { CopyButton } from "@/components/copy-button";
import { DEPARTMENTS, type Department } from "@/lib/types";

const DEPT_LABELS: Record<Department | "all", string> = {
  all: "All",
  engineering: "Engineering",
  product: "Product",
  legal: "Legal",
  finance: "Finance",
  hr: "HR",
  sales: "Sales",
  marketing: "Marketing",
  operations: "Operations",
  security: "Security",
  general: "General",
};

const DEPT_DESC: Record<Department | "all", string> = {
  all: "Universal export — every department combined.",
  engineering: "Code, infra, deploys, on-call. For Eng / DevOps agents.",
  product: "Roadmap, features, prioritization. For PM / Design agents.",
  legal: "Contracts, compliance, NDAs. For Legal agents.",
  finance: "Billing, budgets, payments. For Finance / Accounting agents.",
  hr: "Hiring, onboarding, comp. For People-Ops agents.",
  sales: "Pipeline, accounts, GTM. For Sales agents.",
  marketing: "Brand, comms, campaigns. For Marketing agents.",
  operations: "Inventory, logistics, vendors. For Ops agents.",
  security: "Access, secrets, IR. For Security agents.",
  general: "Cross-cutting facts every agent should have.",
};

type Tab = "all" | Department;

export function SkillsPanel({
  variants,
  counts,
  totalUnits,
  totalEntities,
  totalSources,
}: {
  variants: Record<string, string>;
  counts: Record<Department, number>;
  totalUnits: number;
  totalEntities: number;
  totalSources: number;
}) {
  const [tab, setTab] = useState<Tab>("all");
  const md = variants[tab] ?? variants["all"];
  const filename = tab === "all" ? "SKILLS.md" : `SKILLS-${tab}.md`;
  const downloadUrl = tab === "all" ? "/api/skills" : `/api/skills?department=${tab}`;
  const jsonUrl = tab === "all" ? "/api/skills?format=json" : `/api/skills?department=${tab}&format=json`;

  const tabs: Tab[] = ["all", ...DEPARTMENTS];

  return (
    <div className="mt-6">
      {/* Department tabs */}
      <div className="flex flex-wrap gap-1.5 mb-4 border-b pb-3">
        {tabs.map((t) => {
          const count = t === "all" ? totalUnits : counts[t as Department];
          const active = tab === t;
          return (
            <button
              key={t}
              onClick={() => setTab(t)}
              disabled={count === 0 && t !== "all"}
              className={`text-xs rounded-full px-3 py-1.5 border transition-colors flex items-center gap-1.5 ${
                active
                  ? "bg-[var(--foreground)] text-[var(--background)] border-[var(--foreground)]"
                  : count === 0 && t !== "all"
                    ? "border-[var(--border)] text-[var(--muted-foreground)]/50 cursor-not-allowed"
                    : "border-[var(--border)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
              }`}
            >
              {DEPT_LABELS[t]}
              <span className={`font-mono text-[10px] tabular-nums ${active ? "opacity-90" : "opacity-60"}`}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Description */}
      <div className="rounded-lg border border-[var(--accent)]/30 bg-[var(--accent)]/5 px-4 py-3 text-[12px] text-[var(--muted-foreground)] mb-4">
        <span className="font-medium text-[var(--foreground)]">{DEPT_LABELS[tab]}:</span>{" "}
        {DEPT_DESC[tab]}
        {tab !== "all" && tab !== "general" && (
          <>
            {" "}
            <span className="opacity-80">Includes cross-cutting <code className="font-mono">general</code> knowledge automatically.</span>
          </>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <CopyButton text={md} />
        <a
          href={downloadUrl}
          download={filename}
          className="text-sm rounded-md border px-3 py-2 hover:bg-[var(--muted)]"
        >
          Download {filename}
        </a>
        <a
          href={jsonUrl}
          target="_blank"
          rel="noreferrer"
          className="text-sm rounded-md border px-3 py-2 hover:bg-[var(--muted)]"
        >
          JSON
        </a>
        <div className="ml-auto text-xs text-[var(--muted-foreground)]">
          {totalUnits} total units · {totalEntities} entities · {totalSources} sources
        </div>
      </div>

      {/* Preview */}
      <pre className="rounded-lg border bg-[var(--card)] p-5 text-[12px] leading-relaxed font-mono overflow-auto max-h-[60vh] whitespace-pre-wrap">
        {md}
      </pre>
    </div>
  );
}
