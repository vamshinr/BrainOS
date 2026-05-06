import Link from "next/link";
import { readState } from "@/lib/store";
import { hasGatewayCreds } from "@/lib/ai";
import { formatDate } from "@/lib/utils";
import { SeedButton } from "@/components/seed-button";
import type { UnitKind } from "@/lib/types";

const KIND_LABELS: Record<UnitKind, string> = {
  fact: "fact",
  process: "process",
  decision: "decision",
  ownership: "ownership",
  definition: "definition",
  policy: "policy",
  gotcha: "gotcha",
};

const KIND_TINT: Record<UnitKind, string> = {
  fact: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  process: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  decision: "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  ownership: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  definition: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  policy: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
  gotcha: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
};

export const dynamic = "force-dynamic";

export default async function Home() {
  const state = await readState();
  const hasCreds = hasGatewayCreds();
  const fresh = state.units.filter((u) => !u.stale && !u.supersededBy);

  const byKind = fresh.reduce<Record<string, number>>((acc, u) => {
    acc[u.kind] = (acc[u.kind] ?? 0) + 1;
    return acc;
  }, {});

  const recentUnits = fresh.slice(0, 12);

  return (
    <div className="px-10 py-10 max-w-6xl">
      <header className="mb-10">
        <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
          Brain OS
        </div>
        <h1 className="text-4xl font-semibold tracking-tight">
          The layer between scattered company knowledge and AI agents.
        </h1>
        <p className="mt-3 text-[var(--muted-foreground)] max-w-2xl">
          Pulls atomic knowledge out of Slack, email, tickets, docs and
          meetings. Structures it. Reconciles when things change. Emits an
          executable skill file your agents load.
        </p>
      </header>

      {!hasCreds && (
        <div className="mb-8 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/30 dark:border-amber-800 px-4 py-3 text-sm">
          <div className="font-medium">No AI credentials detected.</div>
          <div className="text-[var(--muted-foreground)] mt-1">
            Set <code className="font-mono">AI_GATEWAY_API_KEY</code> (recommended), or{" "}
            <code className="font-mono">OPENAI_API_KEY</code>, in{" "}
            <code className="font-mono">.env.local</code>, then restart the dev
            server. Optionally set{" "}
            <code className="font-mono">COMPANY_BRAIN_MODEL</code> (default{" "}
            <code className="font-mono">openai/gpt-4o-mini</code>).
          </div>
        </div>
      )}

      <section className="grid grid-cols-4 gap-3 mb-8">
        <Stat label="Sources" value={state.sources.length} />
        <Stat label="Entities" value={state.entities.length} />
        <Stat label="Knowledge units" value={fresh.length} accent />
        <Stat
          label="Superseded"
          value={state.units.length - fresh.length}
          muted
        />
      </section>

      <section className="grid grid-cols-[1fr_280px] gap-8 mb-12">
        <div>
          <SectionTitle>Recent knowledge</SectionTitle>
          {fresh.length === 0 ? (
            <EmptyState hasCreds={hasCreds} />
          ) : (
            <ul className="space-y-2">
              {recentUnits.map((u) => (
                <li
                  key={u.id}
                  className="rounded-lg border bg-[var(--card)] px-4 py-3 hover:border-[var(--accent)]/40 transition-colors"
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={`mt-0.5 inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${KIND_TINT[u.kind]}`}
                    >
                      {KIND_LABELS[u.kind]}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm leading-snug">{u.statement}</div>
                      <div className="mt-1.5 flex items-center gap-2 text-[11px] text-[var(--muted-foreground)]">
                        <span>subject: {u.subject}</span>
                        <span>·</span>
                        <span>conf {u.confidence.toFixed(2)}</span>
                        <span>·</span>
                        <span>{formatDate(u.createdAt)}</span>
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <aside className="space-y-6">
          <div>
            <SectionTitle>By kind</SectionTitle>
            <div className="space-y-1">
              {(Object.keys(KIND_LABELS) as UnitKind[]).map((k) => (
                <div
                  key={k}
                  className="flex items-center justify-between text-sm"
                >
                  <span
                    className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium ${KIND_TINT[k]}`}
                  >
                    {KIND_LABELS[k]}
                  </span>
                  <span className="font-mono text-xs text-[var(--muted-foreground)]">
                    {byKind[k] ?? 0}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <SectionTitle>Sources</SectionTitle>
            {state.sources.length === 0 ? (
              <p className="text-xs text-[var(--muted-foreground)]">
                No sources yet.
              </p>
            ) : (
              <ul className="space-y-2">
                {state.sources.slice(0, 8).map((s) => (
                  <li key={s.id} className="text-xs">
                    <div className="font-medium truncate">{s.title}</div>
                    <div className="text-[var(--muted-foreground)]">
                      {s.kind} · {formatDate(s.capturedAt)}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="pt-4 border-t border-[var(--border)] flex flex-col gap-2">
            <Link
              href="/ingest"
              className="text-sm text-center rounded-md bg-[var(--foreground)] text-[var(--background)] px-3 py-2 hover:opacity-90"
            >
              + Add knowledge
            </Link>
            {state.sources.length === 0 && hasCreds && <SeedButton />}
          </div>
        </aside>
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
  muted,
}: {
  label: string;
  value: number;
  accent?: boolean;
  muted?: boolean;
}) {
  return (
    <div className="rounded-lg border bg-[var(--card)] px-4 py-3">
      <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
        {label}
      </div>
      <div
        className={`mt-1 text-2xl font-semibold tabular-nums ${accent ? "text-[var(--accent)]" : muted ? "text-[var(--muted-foreground)]" : ""}`}
      >
        {value}
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
      {children}
    </h2>
  );
}

function EmptyState({ hasCreds }: { hasCreds: boolean }) {
  return (
    <div className="rounded-lg border border-dashed bg-[var(--muted)]/30 px-6 py-10 text-center">
      <div className="text-sm font-medium">No knowledge yet</div>
      <p className="text-xs text-[var(--muted-foreground)] mt-1 max-w-md mx-auto">
        Drop in a Slack thread, email, ticket, or doc on the Ingest page — or
        seed with a small example company.
      </p>
      <div className="mt-4 flex items-center justify-center gap-2">
        <Link
          href="/ingest"
          className="text-xs rounded-md bg-[var(--foreground)] text-[var(--background)] px-3 py-1.5"
        >
          Ingest
        </Link>
        {hasCreds && <SeedButton />}
      </div>
    </div>
  );
}
