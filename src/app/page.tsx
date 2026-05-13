import Link from "next/link";
import { readState } from "@/lib/store";
import { formatDate } from "@/lib/utils";
import { ResetButton } from "@/components/reset-button";
import { GapAnalysisButton } from "@/components/gap-analysis-button";
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
  const fresh = state.units.filter((u) => !u.stale && !u.supersededBy);
  const isEmpty = state.sources.length === 0 && fresh.length === 0;

  if (isEmpty) {
    return <FirstRunLanding />;
  }

  const byKind = fresh.reduce<Record<string, number>>((acc, u) => {
    acc[u.kind] = (acc[u.kind] ?? 0) + 1;
    return acc;
  }, {});

  const recentUnits = fresh.slice(0, 12);

  return (
    <div className="px-10 py-10 max-w-6xl">
      <div className="grid grid-cols-[1fr_280px] gap-8">
        <div className="min-w-0">
          <header className="mb-10">
            <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
              Brain OS
            </div>
            <h1 className="text-4xl font-semibold tracking-tight">
              Reconciled memory for your AI agents.
            </h1>
            <p className="mt-2 text-lg text-[var(--foreground)]/80 max-w-2xl">
              Stop stuffing your agent&apos;s prompt with noisy RAG chunks.
            </p>
            <p className="mt-3 text-[var(--muted-foreground)] max-w-2xl">
              Atomic, attributable facts extracted from Slack, email, tickets and
              docs. Superseded when things change. Loaded into your agent with
              provenance on every claim — not chunked, not stuffed into a prompt,
              not regenerated on every call.
            </p>
          </header>

          <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-8">
            <Stat label="Sources" value={state.sources.length} />
            <Stat label="Entities" value={state.entities.length} />
            <Stat label="Relationships" value={(state.relationships ?? []).length} accent />
            <Stat label="Knowledge units" value={fresh.length} />
            <Stat
              label="Superseded"
              value={state.units.length - fresh.length}
              muted
            />
          </section>

          <SectionTitle>Recent knowledge</SectionTitle>
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
                    <div className="flex items-start gap-2">
                      <div className="text-sm leading-snug flex-1">{u.statement}</div>
                      {u.disputed && (
                        <span
                          title={`Conflicts with ${u.conflictsWith?.length ?? 0} other unit(s) — click to resolve`}
                          className="shrink-0 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300 border border-red-200 dark:border-red-800"
                        >
                          <span className="size-1.5 rounded-full bg-red-500 inline-block animate-pulse" />
                          Disputed
                        </span>
                      )}
                    </div>
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
        </div>

        <aside className="space-y-6 sticky top-6 self-start max-h-[calc(100vh-3rem)] overflow-y-auto pr-1">
          <div className="flex flex-col gap-2">
            <Link
              href="/ingest"
              className="text-sm text-center rounded-md bg-[var(--foreground)] text-[var(--background)] px-3 py-2 hover:opacity-90"
            >
              + Add knowledge
            </Link>
            <GapAnalysisButton />
            <Link
              href="/failures"
              className="text-sm text-center rounded-md border bg-[var(--card)] px-3 py-2 hover:border-[var(--accent)]/40 transition-colors"
            >
              Agent traps · Loop memory
            </Link>
            <div className="flex items-center justify-between pt-1">
              <Link href="/skills" className="text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] underline underline-offset-2">
                Export SKILLS.md →
              </Link>
              <ResetButton />
            </div>
          </div>

          <div className="pt-4 border-t border-[var(--border)]">
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
        </aside>
      </div>
    </div>
  );
}

function FirstRunLanding() {
  return (
    <div className="px-10 py-12 max-w-5xl">
      <header className="mb-10">
        <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
          Brain OS · agent memory infrastructure
        </div>
        <h1 className="text-4xl font-semibold tracking-tight leading-tight">
          The knowledge layer between scattered company data and AI agents.
        </h1>
        <p className="mt-3 text-lg text-[var(--foreground)]/80 max-w-2xl">
          Stop stuffing your agent&apos;s prompt with noisy RAG chunks.
        </p>
        <p className="mt-4 text-[var(--muted-foreground)] max-w-2xl leading-relaxed">
          Brain OS turns Slack threads, emails, tickets and docs into{" "}
          <strong className="text-[var(--foreground)]">atomic, attributable facts</strong> — reconciled
          when things change, served to your AI agents with{" "}
          <strong className="text-[var(--foreground)]">provenance on every claim</strong>. Not a search
          box. Not a chunked index. A durable memory layer your agents load at
          startup.
        </p>
      </header>

      <section className="mb-10">
        <SectionTitle>What it does</SectionTitle>
        <div className="grid grid-cols-3 gap-3">
          <FeatureCard
            title="Extract atomic facts"
            body="Not chunks. Every fact is a self-contained proposition with a source, a quote, a confidence, a timestamp — the unit format the agent-memory literature has converged on."
          />
          <FeatureCard
            title="Reconcile over time"
            body="When a fact changes, the old one is marked stale with a validTo and supersededBy. When two sources disagree, both are flagged disputed. Your agent never speaks from out-of-date state."
          />
          <FeatureCard
            title="Serve to agents"
            body="Pull the live skill file at agent startup, or query the brain by API. Per-agent scoping. Every claim the agent makes can cite its source."
          />
        </div>
      </section>

      <section className="mb-10">
        <SectionTitle>Why not just RAG?</SectionTitle>
        <div className="rounded-lg border bg-[var(--card)] overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
                <th className="px-4 py-2.5 font-medium">&nbsp;</th>
                <th className="px-4 py-2.5 font-medium">Chunked RAG</th>
                <th className="px-4 py-2.5 font-medium">Enterprise search (Copilot)</th>
                <th className="px-4 py-2.5 font-medium text-[var(--accent)]">Brain OS</th>
              </tr>
            </thead>
            <tbody className="[&_td]:px-4 [&_td]:py-3 [&_td]:align-top [&_tr]:border-b last:[&_tr]:border-b-0">
              <tr>
                <td className="font-medium text-xs">Storage unit</td>
                <td className="text-xs text-[var(--muted-foreground)]">Document chunks + embeddings</td>
                <td className="text-xs text-[var(--muted-foreground)]">Whole documents</td>
                <td className="text-xs">Atomic, attributable facts</td>
              </tr>
              <tr>
                <td className="font-medium text-xs">When facts change</td>
                <td className="text-xs text-[var(--muted-foreground)]">Silently re-retrieves whatever&apos;s in the index</td>
                <td className="text-xs text-[var(--muted-foreground)]">Silently re-summarizes</td>
                <td className="text-xs">Supersedes old fact, flags conflicts as disputed</td>
              </tr>
              <tr>
                <td className="font-medium text-xs">Provenance</td>
                <td className="text-xs text-[var(--muted-foreground)]">&quot;Trust me&quot; : chunk → answer</td>
                <td className="text-xs text-[var(--muted-foreground)]">Citations on the answer</td>
                <td className="text-xs">Source + quote + confidence + timestamp on every fact</td>
              </tr>
              <tr>
                <td className="font-medium text-xs">Built for</td>
                <td className="text-xs text-[var(--muted-foreground)]">Human-readable answers</td>
                <td className="text-xs text-[var(--muted-foreground)]">Employees searching from a UI</td>
                <td className="text-xs">Agents loading durable, attributable context</td>
              </tr>
              <tr>
                <td className="font-medium text-xs">Deployment</td>
                <td className="text-xs text-[var(--muted-foreground)]">Roll your own</td>
                <td className="text-xs text-[var(--muted-foreground)]">SaaS-only, per-seat licensing</td>
                <td className="text-xs">Self-host on one VM, BYO LLM (Claude or vLLM)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-10">
        <SectionTitle>Get started in 3 steps</SectionTitle>
        <ol className="space-y-3">
          <Step
            n={1}
            title="Ingest a fragment of company knowledge"
            body="Paste any Slack thread, email, ticket, or doc. The model extracts atomic units with their source, evidence quote, and confidence."
            cta={{ href: "/ingest", label: "Go to Ingest →" }}
          />
          <Step
            n={2}
            title="Watch reconciliation happen"
            body="Ingest a second source that updates or contradicts the first. Old facts get superseded; conflicts get flagged disputed. The Map shows the resulting entity graph."
            cta={{ href: "/graph", label: "Open Map →" }}
          />
          <Step
            n={3}
            title="Load it into your agent"
            body="Export SKILLS.md and load it as your Claude or GPT agent's memory — or query the brain by API. Every answer the agent gives can cite the underlying fact."
            cta={{ href: "/skills", label: "Get the skill file →" }}
          />
        </ol>
      </section>

      <section className="mb-12">
        <SectionTitle>Explore the rest</SectionTitle>
        <div className="grid grid-cols-2 gap-3">
          <NavCard
            href="/skills"
            title="Skills"
            body="Export an executable SKILLS.md file — the version of your company an AI agent loads."
          />
          <NavCard
            href="/slack"
            title="Slack MCP"
            body="Connect a Slack workspace so brainOS can listen to channels and auto-answer threads."
          />
          <NavCard
            href="/metrics"
            title="GPU metrics"
            body="If you're serving your own model on an AMD MI300X (or any vLLM endpoint), live throughput stats live here."
          />
          <NavCard
            href="/ingest"
            title="Ingest"
            body="Text, file uploads, and image ingestion (screenshots of whiteboards, slides, diagrams)."
          />
          <NavCard
            href="/failures"
            title="Agent traps · Loop memory"
            body="Paste a thrashing agent transcript. BrainOS extracts the loop as a durable gotcha and adds it to SKILLS.md so the next agent skips it."
          />
        </div>
      </section>

      <section className="rounded-lg border bg-[var(--muted)]/30 px-6 py-5">
        <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
          Tip
        </div>
        <p className="text-sm leading-relaxed">
          Start with one Slack thread your agent currently has no idea about.
          Paste it into{" "}
          <Link href="/ingest" className="underline underline-offset-2">
            Ingest
          </Link>
          , then ingest a second message that updates it. The reconciliation
          view will show the old fact superseded, the new one fresh, and the
          provenance preserved on both — that&apos;s the loop your agent needs.
        </p>
      </section>
    </div>
  );
}

function FeatureCard({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border bg-[var(--card)] px-4 py-4">
      <div className="text-sm font-semibold mb-1">{title}</div>
      <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
        {body}
      </p>
    </div>
  );
}

function Step({
  n,
  title,
  body,
  cta,
}: {
  n: number;
  title: string;
  body: string;
  cta: { href: string; label: string };
}) {
  return (
    <li className="rounded-lg border bg-[var(--card)] px-5 py-4 flex items-start gap-4">
      <div className="size-7 shrink-0 rounded-full bg-[var(--accent)]/15 text-[var(--accent)] grid place-items-center text-sm font-semibold">
        {n}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold">{title}</div>
        <p className="text-xs text-[var(--muted-foreground)] mt-1 leading-relaxed">
          {body}
        </p>
      </div>
      <Link
        href={cta.href}
        className="shrink-0 text-xs rounded-md bg-[var(--foreground)] text-[var(--background)] px-3 py-2 hover:opacity-90"
      >
        {cta.label}
      </Link>
    </li>
  );
}

function NavCard({
  href,
  title,
  body,
}: {
  href: string;
  title: string;
  body: string;
}) {
  return (
    <Link
      href={href}
      className="rounded-lg border bg-[var(--card)] px-4 py-4 hover:border-[var(--accent)]/40 transition-colors"
    >
      <div className="text-sm font-semibold mb-1">{title}</div>
      <p className="text-xs text-[var(--muted-foreground)] leading-relaxed">
        {body}
      </p>
    </Link>
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
