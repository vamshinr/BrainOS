import Link from "next/link";
import { readState } from "@/lib/store";
import { generateSkills } from "@/lib/skills";
import { CopyButton } from "@/components/copy-button";

export const dynamic = "force-dynamic";

export default async function SkillsPage() {
  const state = await readState();
  const md = generateSkills(state);
  const fresh = state.units.filter((u) => !u.stale && !u.supersededBy);

  return (
    <div className="px-10 py-10 max-w-5xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Skills export
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">
        SKILLS.md — the agent interface.
      </h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-2xl">
        This file is the output BrainOS produces for every other AI agent to consume.
        It distills all ingested company knowledge into atomic, agent-readable instructions.
        Any agent that loads it operates with full company context from day one.
      </p>

      {/* ── How to use ── */}
      <div className="mt-8 space-y-4">
        <h2 className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
          How to load this into an agent
        </h2>

        <div className="grid grid-cols-3 gap-3">
          <UsageCard
            title="Claude Code"
            badge="CLAUDE.md"
            description="Claude Code auto-loads CLAUDE.md from your project root. Drop SKILLS.md content there and every Claude Code session starts with full company context."
            code={`# In your project root:
cat SKILLS.md >> CLAUDE.md
# or symlink it:
ln -s SKILLS.md CLAUDE.md`}
          />
          <UsageCard
            title="Anthropic SDK"
            badge="system prompt"
            description="Inject at agent startup as the system prompt prefix. The agent then answers any task with company knowledge already loaded."
            code={`import anthropic, { readFileSync }
skills = open("SKILLS.md").read()
client.messages.create(
  system=skills,
  messages=[...]
)`}
          />
          <UsageCard
            title="Any OpenAI-compatible agent"
            badge="messages[0]"
            description="Pass SKILLS.md as the first system message. Works with LangChain, CrewAI, AutoGen, or any agent framework that accepts a system prompt."
            code={`skills = open("SKILLS.md").read()
messages = [
  {"role": "system", "content": skills},
  {"role": "user", "content": task},
]`}
          />
        </div>

        {/* API endpoint callout */}
        <div className="rounded-lg border bg-[var(--card)] px-4 py-3 font-mono text-[12px]">
          <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
            Fetch programmatically — always returns the latest brain state
          </div>
          <div className="space-y-1">
            <div>
              <span className="text-emerald-600 dark:text-emerald-400">GET</span>
              {" "}<span className="text-[var(--foreground)]">/api/skills</span>
              <span className="text-[var(--muted-foreground)] ml-3">→ SKILLS.md (Markdown, for agents)</span>
            </div>
            <div>
              <span className="text-emerald-600 dark:text-emerald-400">GET</span>
              {" "}<span className="text-[var(--foreground)]">/api/skills?format=json</span>
              <span className="text-[var(--muted-foreground)] ml-3">→ structured JSON (for programmatic use)</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Why this is not just a RAG dump ── */}
      <div className="mt-6 rounded-lg border border-[var(--accent)]/30 bg-[var(--accent)]/5 px-5 py-4 text-[13px]">
        <div className="font-semibold mb-1">brain.json → SKILLS.md: what the transform does</div>
        <p className="text-[var(--muted-foreground)] leading-relaxed">
          brain.json contains raw provenance: source IDs, evidence quotes, timestamps, stale flags,
          ChromaDB vectors. An agent cannot act on that. SKILLS.md strips all internal bookkeeping
          and produces only what an agent needs: clean atomic statements, grouped by kind, with
          low-confidence items flagged <code className="font-mono">~</code> so the agent knows when
          to verify. Superseded knowledge is listed separately for audit — it never silently vanishes.
          The result is a file small enough to fit in any model&apos;s context window, updated
          automatically every time knowledge is ingested.
        </p>
      </div>

      {/* ── Download / copy ── */}
      <div className="mt-6 flex items-center gap-3">
        <CopyButton text={md} />
        <a
          href="/api/skills"
          download="SKILLS.md"
          className="text-sm rounded-md border px-3 py-2 hover:bg-[var(--muted)]"
        >
          Download SKILLS.md
        </a>
        <a
          href="/api/skills?format=json"
          target="_blank"
          rel="noreferrer"
          className="text-sm rounded-md border px-3 py-2 hover:bg-[var(--muted)]"
        >
          JSON endpoint
        </a>
        <div className="ml-auto text-xs text-[var(--muted-foreground)]">
          {fresh.length} units · {state.entities.length} entities · {state.sources.length} sources
          {(state.relationships ?? []).length > 0 && ` · ${state.relationships.length} relationships`}
        </div>
      </div>

      {fresh.length === 0 && (
        <div className="mt-6 rounded-lg border border-dashed bg-[var(--muted)]/30 px-6 py-8 text-sm text-center">
          No knowledge to export yet.{" "}
          <Link href="/ingest" className="underline">
            Ingest something
          </Link>
          {" "}to generate the skills file.
        </div>
      )}

      {/* ── SKILLS.md preview ── */}
      {fresh.length > 0 && (
        <pre className="mt-6 rounded-lg border bg-[var(--card)] p-5 text-[12px] leading-relaxed font-mono overflow-auto max-h-[60vh] whitespace-pre-wrap">
          {md}
        </pre>
      )}
    </div>
  );
}

function UsageCard({
  title,
  badge,
  description,
  code,
}: {
  title: string;
  badge: string;
  description: string;
  code: string;
}) {
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
