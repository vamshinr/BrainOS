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
        Skills
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">
        Executable skill file for AI agents.
      </h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-2xl">
        Drop this file into any agent that supports skills (Claude Code,
        Anthropic SDK, custom). It compresses the company&apos;s tribal
        knowledge into atomic instructions an agent can act on.
      </p>

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
          View JSON
        </a>
        <div className="ml-auto text-xs text-[var(--muted-foreground)]">
          {fresh.length} units · {state.entities.length} entities ·{" "}
          {state.sources.length} sources
        </div>
      </div>

      {fresh.length === 0 && (
        <div className="mt-6 rounded-lg border border-dashed bg-[var(--muted)]/30 px-6 py-8 text-sm text-center">
          No knowledge to export yet.{" "}
          <Link href="/ingest" className="underline">
            Ingest something
          </Link>
          .
        </div>
      )}

      <pre className="mt-6 rounded-lg border bg-[var(--card)] p-5 text-[12px] leading-relaxed font-mono overflow-auto max-h-[70vh] whitespace-pre-wrap">
        {md}
      </pre>
    </div>
  );
}
