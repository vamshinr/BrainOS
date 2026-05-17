import Link from "next/link";
import type { ReactNode } from "react";
import { FileText, Plug, Radio } from "lucide-react";
import { readState } from "@/lib/store";
import { formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

export default async function OnboardingPage() {
  const state = await readState();
  const docSources = state.sources.filter((s) => s.kind !== "slack");
  const slackSources = state.sources.filter((s) => s.kind === "slack");
  const decisions = state.units.filter((u) => !u.stale && !u.supersededBy && u.kind === "decision");

  return (
    <div className="px-4 sm:px-6 md:px-10 py-6 md:py-10 max-w-5xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Customer onboarding
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">
            Bring a customer workspace online.
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-[var(--muted-foreground)]">
            Start with durable docs, then route Slack into BrainOS so high-confidence decisions can reach the executive alert surface.
          </p>
        </div>
        <Link
          href="/slack"
          className="inline-flex items-center justify-center gap-2 rounded-md bg-[var(--foreground)] px-3 py-2 text-sm text-[var(--background)] hover:opacity-90"
        >
          <Plug size={16} />
          Configure Slack
        </Link>
      </div>

      <section className="mt-7 grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-5">
        <div className="space-y-4">
          <SetupStep
            n={1}
            icon={<FileText size={18} />}
            title="Ingest source-of-truth docs"
            status={docSources.length > 0 ? `${docSources.length} source${docSources.length === 1 ? "" : "s"} ingested` : "Not started"}
            body="Upload policy docs, runbooks, PDFs, meeting notes, and diagrams. BrainOS will extract atomic facts, owners, policies, and decisions with evidence."
            cta={{ href: "/ingest", label: "Open ingest" }}
            done={docSources.length > 0}
          />
          <SetupStep
            n={2}
            icon={<Radio size={18} />}
            title="Route Slack realtime"
            status={slackSources.length > 0 ? `${slackSources.length} Slack source${slackSources.length === 1 ? "" : "s"}` : "Waiting for Slack"}
            body="Map approved channels to departments, enable realtime ingest channels, and enable CEO decision alert channels for executive-critical streams."
            cta={{ href: "/slack", label: "Open Slack MCP" }}
            done={slackSources.length > 0}
          />
        </div>

        <aside className="rounded-lg border bg-[var(--card)] p-4 h-fit">
          <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
            Readiness
          </div>
          <dl className="space-y-3 text-sm">
            <Metric label="Docs" value={docSources.length} />
            <Metric label="Slack sources" value={slackSources.length} />
            <Metric label="Current decisions" value={decisions.length} />
          </dl>
          <div className="mt-4 border-t pt-4">
            <div className="text-xs font-medium">Latest source</div>
            {state.sources[0] ? (
              <div className="mt-1 text-xs text-[var(--muted-foreground)]">
                <div className="truncate text-[var(--foreground)]">{state.sources[0].title}</div>
                <div>{state.sources[0].kind} · {formatDate(state.sources[0].capturedAt)}</div>
              </div>
            ) : (
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">No sources ingested yet.</p>
            )}
          </div>
        </aside>
      </section>
    </div>
  );
}

function SetupStep({
  n,
  icon,
  title,
  status,
  body,
  cta,
  done,
}: {
  n: number;
  icon: ReactNode;
  title: string;
  status: string;
  body: string;
  cta: { href: string; label: string };
  done: boolean;
}) {
  return (
    <section className="rounded-lg border bg-[var(--card)] p-4">
      <div className="flex items-start gap-3">
        <div className="grid size-9 shrink-0 place-items-center rounded-md border bg-[var(--background)] text-[var(--muted-foreground)]">
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-[var(--muted-foreground)]">0{n}</span>
              <h2 className="font-semibold">{title}</h2>
            </div>
            <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
              done
                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
                : "bg-[var(--muted)] text-[var(--muted-foreground)]"
            }`}>
              {status}
            </span>
          </div>
          <p className="mt-2 text-sm leading-relaxed text-[var(--muted-foreground)]">
            {body}
          </p>
          <Link
            href={cta.href}
            className="mt-4 inline-flex rounded-md border px-3 py-2 text-sm hover:bg-[var(--muted)]/60"
          >
            {cta.label}
          </Link>
        </div>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-[var(--muted-foreground)]">{label}</dt>
      <dd className="font-mono font-semibold tabular-nums">{value}</dd>
    </div>
  );
}
