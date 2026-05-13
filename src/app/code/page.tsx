import Link from "next/link";
import { readState } from "@/lib/store";
import { formatDate } from "@/lib/utils";
import type { Source, Unit } from "@/lib/store";
import { FileTree } from "@/components/file-tree";
import { SymbolSearch } from "@/components/symbol-search";

export const dynamic = "force-dynamic";

interface PageProps {
  // Next.js 16 — searchParams is a Promise; await it before reading.
  searchParams: Promise<{ src?: string }>;
}

export default async function CodePage({ searchParams }: PageProps) {
  const { src } = await searchParams;
  const state = await readState();

  const codeSources = state.sources
    .filter((s) => s.kind === "code" && s.codebase)
    .sort((a, b) => (b.capturedAt ?? "").localeCompare(a.capturedAt ?? ""));

  if (codeSources.length === 0) {
    return <EmptyState />;
  }

  if (!src) {
    return <CodebaseList codeSources={codeSources} />;
  }

  const selected = codeSources.find((s) => s.id === src);
  if (!selected) {
    return (
      <div className="px-10 py-10 max-w-5xl">
        <p className="text-sm text-[var(--muted-foreground)]">
          Codebase <code className="font-mono">{src}</code> not found.{" "}
          <Link className="underline" href="/code">Back to list →</Link>
        </p>
      </div>
    );
  }

  // Find units linked to this code source via evidence[].sourceId. These are
  // the ownership/decision/process facts extracted from CODEOWNERS + READMEs +
  // ADRs during ingest.
  const sourceUnits = state.units.filter((u) => {
    const ev = u.evidence ?? [];
    return ev.some((e) => e?.sourceId === selected.id) && !u.stale && !u.supersededBy;
  });

  return <CodebaseDetail source={selected} units={sourceUnits} />;
}

// ─────────────────────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="px-10 py-10 max-w-3xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Code
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Codebase map</h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-2xl">
        Ingest a <code className="font-mono">.zip</code> of your repo (or a single
        code/doc file) to build a lightweight map: file tree, ownership from
        CODEOWNERS, rationale facts from READMEs / ADRs / RFCs, and entity↔path
        links into your existing knowledge graph.
      </p>
      <p className="mt-3 text-[var(--muted-foreground)] max-w-2xl">
        We don&apos;t embed code bodies — that&apos;s Cursor&apos;s job. We
        capture <em>why</em> the code is the way it is.
      </p>
      <div className="mt-6">
        <Link
          href="/ingest"
          className="inline-flex items-center rounded-md bg-[var(--foreground)] text-[var(--background)] px-4 py-2 text-sm font-medium hover:opacity-90"
        >
          Ingest a codebase →
        </Link>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function CodebaseList({ codeSources }: { codeSources: Source[] }) {
  return (
    <div className="px-10 py-10 max-w-5xl">
      <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
        Code
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">Codebase map</h1>
      <p className="mt-2 text-[var(--muted-foreground)] max-w-2xl">
        {codeSources.length} ingested codebase{codeSources.length === 1 ? "" : "s"}.
        Click one to see its file tree, ownership, ADR-derived decisions, and
        entity↔path links.
      </p>

      <ul className="mt-8 space-y-3">
        {codeSources.map((s) => {
          const cb = s.codebase!;
          const topLangs = Object.entries(cb.byLanguage).slice(0, 5);
          return (
            <li key={s.id}>
              <Link
                href={`/code?src=${encodeURIComponent(s.id)}`}
                className="block rounded-lg border bg-[var(--card)] px-5 py-4 hover:border-[var(--accent)]/40 transition-colors"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate">{s.title}</div>
                    <div className="text-[11px] text-[var(--muted-foreground)] mt-0.5">
                      ingested {formatDate(s.capturedAt)} · id <code className="font-mono">{s.id}</code>
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-2xl font-semibold tabular-nums">
                      {cb.totalFiles}
                    </div>
                    <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
                      files{cb.truncated ? " (capped)" : ""}
                    </div>
                  </div>
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  {topLangs.map(([lang, n]) => (
                    <span
                      key={lang}
                      className="inline-flex items-center gap-1 rounded-full bg-[var(--muted)] px-2 py-0.5 text-[11px]"
                    >
                      <span className="font-mono">{lang}</span>
                      <span className="text-[var(--muted-foreground)]">{n}</span>
                    </span>
                  ))}
                  {(cb.rationaleFilesExtracted ?? 0) > 0 && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300 px-2 py-0.5 text-[11px]">
                      {cb.rationaleFilesExtracted} rationale extracted
                    </span>
                  )}
                  {Object.keys(cb.entityPaths ?? {}).length > 0 && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300 px-2 py-0.5 text-[11px]">
                      {Object.keys(cb.entityPaths!).length} entity↔path links
                    </span>
                  )}
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function CodebaseDetail({ source, units }: { source: Source; units: Unit[] }) {
  const cb = source.codebase!;
  const files = cb.files ?? [];
  const entityPaths = cb.entityPaths ?? {};

  // Partition units by what they came from
  const ownershipUnits = units.filter((u) => u.kind === "ownership");
  const decisionUnits  = units.filter((u) => u.kind === "decision");
  const otherUnits     = units.filter((u) => u.kind !== "ownership" && u.kind !== "decision");

  // ADR-derived units: ones whose evidence has a path under /adr/, /rfc/, etc.
  const adrPathRe = /\/(adr|adrs|rfc|rfcs|decisions|decision-log)\//i;
  const adrUnits = units.filter((u) =>
    (u.evidence ?? []).some((e) => {
      const p = (e as { path?: string })?.path ?? "";
      return adrPathRe.test(p);
    }),
  );

  return (
    <div className="px-10 py-10 max-w-5xl">
      <div className="flex items-center gap-2 mb-2">
        <Link
          href="/code"
          className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          ← All codebases
        </Link>
      </div>
      <h1 className="text-3xl font-semibold tracking-tight">{source.title}</h1>
      <p className="mt-2 text-[var(--muted-foreground)] text-sm">
        Ingested {formatDate(source.capturedAt)} · id{" "}
        <code className="font-mono">{source.id}</code>
        {cb.truncated && (
          <span className="ml-2 inline-flex items-center rounded bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 px-1.5 py-0.5 text-[10px] font-medium">
            file list truncated at {cb.totalFiles}
          </span>
        )}
      </p>

      {/* Stat row */}
      <section className="grid grid-cols-5 gap-3 mt-6 mb-4">
        <Stat label="Files" value={cb.totalFiles} />
        <Stat label="Languages" value={Object.keys(cb.byLanguage).length} />
        <Stat label="Outlines built" value={cb.outlinesBuilt ?? 0} accent />
        <Stat label="Rationale extracted" value={cb.rationaleFilesExtracted ?? 0} />
        <Stat label="Ownership facts" value={ownershipUnits.length} />
      </section>
      <section className="grid grid-cols-4 gap-3 mb-8">
        <Stat label="Symbols indexed" value={Object.keys(cb.symbolIndex ?? {}).length} />
        <Stat label="Import edges" value={cb.importGraph?.stats.internalEdges ?? 0} />
        <Stat label="Call edges" value={cb.callEdges?.length ?? 0} />
        <Stat label="Module summaries" value={cb.moduleSummaries?.length ?? 0} accent />
      </section>

      {/* Module summaries (auto-wiki) */}
      {cb.moduleSummaries && cb.moduleSummaries.length > 0 && (
        <section className="mb-10">
          <SectionTitle>Modules (auto-wiki)</SectionTitle>
          <p className="text-xs text-[var(--muted-foreground)] mb-3 max-w-2xl">
            LLM-generated 2-3 sentence overviews per top-level directory, built
            from README + outline + top symbols. Used as fallback context in
            <code className="mx-1 font-mono">/ask</code> when a question
            mentions a module by name.
          </p>
          <ul className="space-y-2">
            {cb.moduleSummaries.map((m) => (
              <li key={m.dir} className="rounded border bg-[var(--card)] px-4 py-3">
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="font-mono text-sm font-medium">{m.dir}/</span>
                  <span className="text-[10px] text-[var(--muted-foreground)] tabular-nums">
                    {m.fileCount} files · {Object.entries(m.languages).slice(0, 3).map(([k, v]) => `${k}:${v}`).join(", ")}
                  </span>
                </div>
                <p className="text-sm text-[var(--foreground)]/90">{m.summary}</p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Symbol search */}
      {cb.symbolIndex && Object.keys(cb.symbolIndex).length > 0 && (
        <section className="mb-10">
          <SectionTitle>Find a symbol</SectionTitle>
          <p className="text-xs text-[var(--muted-foreground)] mb-3 max-w-2xl">
            Reverse index built from per-file outlines. Search by name to find
            every definition across the codebase.
          </p>
          <SymbolSearch index={cb.symbolIndex} />
        </section>
      )}

      {/* Import graph hubs + external deps */}
      {cb.importGraph && cb.importGraph.stats.internalEdges > 0 && (
        <section className="mb-10">
          <SectionTitle>Import graph</SectionTitle>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
                Hubs (most imported-by)
              </div>
              <ul className="space-y-1">
                {cb.importGraph.stats.hubs.slice(0, 10).map((h) => (
                  <li key={h.path} className="flex items-baseline gap-2 text-xs">
                    <span className="font-mono truncate flex-1">{h.path}</span>
                    <span className="tabular-nums text-[var(--accent)]">{h.fanIn}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-2">
                External deps (top by count)
              </div>
              <ul className="space-y-1">
                {Object.entries(cb.importGraph.external).slice(0, 10).map(([dep, n]) => (
                  <li key={dep} className="flex items-baseline gap-2 text-xs">
                    <span className="font-mono truncate flex-1">{dep}</span>
                    <span className="tabular-nums text-[var(--muted-foreground)]">{n}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      )}

      {/* Call graph — top callees */}
      {cb.callEdges && cb.callEdges.length > 0 && (
        <section className="mb-10">
          <SectionTitle>Call graph — top callees</SectionTitle>
          <p className="text-xs text-[var(--muted-foreground)] mb-3 max-w-2xl">
            Caller→callee edges resolved against the symbol index. Python is
            via <code className="font-mono">ast</code>; other languages use
            regex (lower confidence, marked with{" "}
            <span className="font-mono">~</span>).
          </p>
          <CallGraphTop edges={cb.callEdges} />
        </section>
      )}

      {/* Languages + Top dirs */}
      <section className="grid grid-cols-2 gap-6 mb-10">
        <Bucket title="By language" entries={cb.byLanguage} />
        <Bucket title="Top-level dirs" entries={cb.topLevelDirs} />
      </section>

      {/* Entity ↔ Path */}
      {Object.keys(entityPaths).length > 0 && (
        <section className="mb-10">
          <SectionTitle>Entity ↔ Path</SectionTitle>
          <p className="text-xs text-[var(--muted-foreground)] mb-3 max-w-2xl">
            Existing entities matched to file paths by token overlap — the
            bridge that lets agents jump from a fact to a code location.
          </p>
          <ul className="space-y-1.5">
            {Object.entries(entityPaths).slice(0, 50).map(([ent, paths]) => (
              <li
                key={ent}
                className="rounded border bg-[var(--card)] px-3 py-2 text-sm flex items-baseline gap-3"
              >
                <span className="font-medium">{ent}</span>
                <span className="text-[var(--muted-foreground)] font-mono text-xs truncate">
                  {paths.slice(0, 5).join(", ")}
                  {paths.length > 5 && ` … (+${paths.length - 5})`}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Ownership facts (from CODEOWNERS) */}
      {ownershipUnits.length > 0 && (
        <section className="mb-10">
          <SectionTitle>Ownership (from CODEOWNERS)</SectionTitle>
          <ul className="space-y-1.5">
            {ownershipUnits.slice(0, 30).map((u) => (
              <li key={u.id} className="rounded border bg-[var(--card)] px-3 py-2 text-sm">
                {u.statement}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* ADR / RFC decisions */}
      {adrUnits.length > 0 && (
        <section className="mb-10">
          <SectionTitle>Decisions extracted from ADRs / RFCs</SectionTitle>
          <ul className="space-y-2">
            {adrUnits.slice(0, 30).map((u) => {
              const path = (u.evidence ?? [])
                .map((e) => (e as { path?: string })?.path ?? "")
                .find((p) => adrPathRe.test(p));
              return (
                <li key={u.id} className="rounded border bg-[var(--card)] px-3 py-2 text-sm">
                  <div className="flex items-start gap-2">
                    <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300">
                      {u.kind}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div>{u.statement}</div>
                      {path && (
                        <div className="mt-1 text-[10px] font-mono text-[var(--muted-foreground)] truncate">
                          {path}
                        </div>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {/* Other rationale facts (READMEs, CONTRIBUTING, etc.) */}
      {otherUnits.length > 0 && (
        <section className="mb-10">
          <SectionTitle>Other rationale facts</SectionTitle>
          <ul className="space-y-1.5">
            {otherUnits.slice(0, 20).map((u) => (
              <li key={u.id} className="rounded border bg-[var(--card)] px-3 py-2 text-sm">
                <span className="inline-flex items-center rounded px-1.5 py-0.5 mr-2 text-[10px] font-medium bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                  {u.kind}
                </span>
                {u.statement}
              </li>
            ))}
          </ul>
        </section>
      )}

      {decisionUnits.length > 0 && adrUnits.length === 0 && (
        <section className="mb-10">
          <SectionTitle>Decisions</SectionTitle>
          <ul className="space-y-1.5">
            {decisionUnits.slice(0, 20).map((u) => (
              <li key={u.id} className="rounded border bg-[var(--card)] px-3 py-2 text-sm">
                {u.statement}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* File tree — hierarchical, collapsible */}
      {files.length > 0 && (
        <section className="mb-10">
          <SectionTitle>File tree</SectionTitle>
          <p className="text-xs text-[var(--muted-foreground)] mb-3">
            Folders are collapsible. Each row shows category, language, and size.
            Top-level dirs are expanded by default.
          </p>
          <FileTree files={files} />
        </section>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className="rounded-lg border bg-[var(--card)] px-4 py-3">
      <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
        {label}
      </div>
      <div
        className={`mt-1 text-2xl font-semibold tabular-nums ${accent ? "text-[var(--accent)]" : ""}`}
      >
        {value}
      </div>
    </div>
  );
}

function Bucket({ title, entries }: { title: string; entries: Record<string, number> }) {
  const sorted = Object.entries(entries).sort((a, b) => b[1] - a[1]);
  const max = sorted[0]?.[1] ?? 0;
  return (
    <div>
      <SectionTitle>{title}</SectionTitle>
      <ul className="space-y-1">
        {sorted.slice(0, 12).map(([k, v]) => (
          <li key={k} className="flex items-center gap-3 text-xs">
            <div className="w-28 truncate font-mono">{k}</div>
            <div className="flex-1 h-2 rounded-full bg-[var(--muted)] overflow-hidden">
              <div
                className="h-full bg-[var(--accent)]/70"
                style={{ width: `${max > 0 ? Math.round((v / max) * 100) : 0}%` }}
              />
            </div>
            <div className="w-8 text-right tabular-nums text-[var(--muted-foreground)]">{v}</div>
          </li>
        ))}
      </ul>
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

function CallGraphTop({ edges }: { edges: NonNullable<import("@/lib/store").CodebaseSummary["callEdges"]> }) {
  // Group by callee — "who calls X the most"
  const byCallee = new Map<string, { count: number; ambiguous: boolean; sample: string }>();
  for (const e of edges) {
    const cur = byCallee.get(e.callee);
    if (cur) {
      cur.count += 1;
      cur.ambiguous = cur.ambiguous || e.ambiguous;
    } else {
      byCallee.set(e.callee, { count: 1, ambiguous: e.ambiguous, sample: e.to });
    }
  }
  const top = Array.from(byCallee.entries())
    .sort((a, b) => b[1].count - a[1].count)
    .slice(0, 20);
  return (
    <ul className="space-y-1">
      {top.map(([name, info]) => (
        <li key={name} className="flex items-baseline gap-3 text-xs">
          <span className="font-mono font-medium flex-shrink-0">
            {info.ambiguous && <span className="text-amber-600 dark:text-amber-400 mr-1">~</span>}
            {name}
          </span>
          <span className="text-[var(--muted-foreground)] font-mono truncate flex-1">{info.sample}</span>
          <span className="tabular-nums text-[var(--accent)]">{info.count}×</span>
        </li>
      ))}
    </ul>
  );
}

