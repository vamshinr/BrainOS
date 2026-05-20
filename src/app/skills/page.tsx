import Link from "next/link";
import { readState } from "@/lib/store";
import { generateSkills, departmentCounts } from "@/lib/skills";
import { DEPARTMENTS } from "@/lib/types";
import { SkillsPanel } from "@/components/skills-panel";

export const dynamic = "force-dynamic";

export default async function SkillsPage() {
  const state = await readState();
  const fresh = state.units.filter((u) => !u.stale && !u.supersededBy);
  const counts = departmentCounts(state);

  // Pre-render every department's markdown so the client can switch instantly
  // without a round-trip. Cheap — generateSkills is a pure string build.
  const variants: Record<string, string> = { all: generateSkills(state) };
  for (const d of DEPARTMENTS) {
    variants[d] = generateSkills(state, d);
  }

  return (
    <div className="px-4 sm:px-6 md:px-10 py-6 md:py-10 max-w-5xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Skills export
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">
        SKILLS.md — the agent interface.
      </h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-2xl">
        BrainOS distills ingested knowledge into atomic, agent-readable instructions.
        Pick a department to give an agent only what its function needs — a Legal agent
        doesn&apos;t need finance ledgers, a Finance agent doesn&apos;t need on-call runbooks.
      </p>

      {fresh.length === 0 ? (
        <div className="mt-8 rounded-lg border border-dashed bg-[var(--muted)]/30 px-6 py-10 text-sm text-center">
          No knowledge to export yet.{" "}
          <Link href="/ingest" className="underline">Ingest something</Link>{" "}
          to generate the skills file.
        </div>
      ) : (
        <SkillsPanel
          variants={variants}
          counts={counts}
          totalUnits={fresh.length}
          totalEntities={state.entities.length}
          totalSources={state.sources.length}
        />
      )}

      {/* ── How to use (static, doesn't depend on department) ── */}
      <div className="mt-10">
        <h2 className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-3">
          How to load this into an agent
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <UsageCard
            title="Claude Code"
            badge="CLAUDE.md"
            description="Drop the chosen department's SKILLS.md into your project root as CLAUDE.md. Every Claude Code session starts pre-loaded."
            code={`# Engineering team:
curl /api/skills?department=engineering > CLAUDE.md`}
          />
          <UsageCard
            title="Anthropic SDK"
            badge="system prompt"
            description="Inject at agent startup. Pick the department matching the agent's role — Legal agent gets Legal+General, no Finance."
            code={`skills = open("SKILLS-legal.md").read()
client.messages.create(
  system=skills,
  messages=[...]
)`}
          />
          <UsageCard
            title="Multi-agent system"
            badge="role-aware"
            description="Each specialized agent loads only its department's skills file. Smaller context, lower cost, no leakage between functions."
            code={`agents = {
  "legal":   load("?department=legal"),
  "finance": load("?department=finance"),
  "eng":     load("?department=engineering"),
}`}
          />
        </div>
      </div>

      {/* ── API endpoints ── */}
      <div className="mt-6 rounded-lg border bg-[var(--card)] px-4 py-3 font-mono text-[12px]">
        <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
          API endpoints
        </div>
        <div className="space-y-1">
          <Endpoint method="GET" path="/api/skills" desc="full SKILLS.md (all departments)" />
          <Endpoint method="GET" path="/api/skills?department=legal" desc="Legal + General only" />
          <Endpoint method="GET" path="/api/skills?format=json" desc="structured JSON for programmatic use" />
          <Endpoint method="GET" path="/api/skills?department=hr&format=json" desc="HR-only JSON" />
        </div>
      </div>
    </div>
  );
}

function UsageCard({
  title, badge, description, code,
}: { title: string; badge: string; description: string; code: string }) {
  return (
    <div className="rounded-lg border bg-[var(--card)] px-4 py-3 flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-sm font-semibold">{title}</span>
        <span className="font-mono text-[10px] rounded bg-[var(--accent)]/10 text-[var(--accent)] px-1.5 py-0.5">
          {badge}
        </span>
      </div>
      <p className="text-[11px] text-[var(--muted-foreground)] leading-relaxed">{description}</p>
      <pre className="mt-auto rounded bg-[var(--muted)]/40 px-3 py-2 text-[10px] font-mono leading-relaxed overflow-auto whitespace-pre">
        {code}
      </pre>
    </div>
  );
}

function Endpoint({ method, path, desc }: { method: string; path: string; desc: string }) {
  return (
    <div>
      <span className="text-emerald-600 dark:text-emerald-400">{method}</span>
      {" "}<span className="text-[var(--foreground)]">{path}</span>
      <span className="text-[var(--muted-foreground)] ml-3">→ {desc}</span>
    </div>
  );
}
