import type { State, Unit } from "./store";
import { DEPARTMENTS, type Department, type UnitKind } from "./types";

/*
 * BrainOS skill generation contract:
 * - Skills are compact operational memory for agents, not documentation dumps.
 * - Keep facts atomic, department-scoped, temporal-aware, confidence-aware, and source-backed.
 * - Separate ownership, policies, processes, decisions, gotchas, definitions, and facts.
 * - Generate imperative agent rules only from high-confidence operational units.
 */

// ── Sector keyword map (offline, no LLM required) ─────────────────────────────
const SECTOR_KEYWORDS: Record<string, string[]> = {
  HR: ["hire", "onboard", "employee", "leave", "vacation", "headcount", "people", "payroll", "benefit", "hr", "recruit", "termination"],
  Legal: ["compliance", "contract", "legal", "liability", "regulation", "gdpr", "privacy", "terms", "law", "audit", "ip", "copyright"],
  Finance: ["budget", "invoice", "payment", "refund", "stripe", "billing", "expense", "revenue", "arr", "finance", "cost", "pricing", "price", "payout"],
  Engineering: ["deploy", "server", "api", "code", "bug", "repository", "database", "infrastructure", "endpoint", "vllm", "docker", "gpu", "hip", "service", "migration", "deprecat", "backend", "frontend", "port", "runbook"],
  Product: ["feature", "roadmap", "launch", "customer", "feedback", "product", "release", "v1", "v2", "sprint", "backlog", "ux", "design", "prototype"],
  "Supply Chain": ["supplier", "inventory", "warehouse", "shipping", "logistics", "stock", "vendor", "procurement", "fulfillment"],
};

const KIND_ORDER: UnitKind[] = ["ownership", "definition", "policy", "process", "decision", "gotcha", "fact"];

const KIND_LABELS: Record<UnitKind, string> = {
  ownership: "Ownership",
  definition: "Definitions",
  policy: "Policies",
  process: "Processes",
  decision: "Decisions",
  gotcha: "Gotchas",
  fact: "Facts",
};

const OPERATIONAL_KIND_ORDER: UnitKind[] = ["definition", "fact"];
const MIN_SKILL_CONFIDENCE = 0.5;

const DEPARTMENT_RELEVANCE_KEYWORDS: Record<Department, string[]> = {
  engineering: ["api", "backend", "billing-svc", "deploy", "endpoint", "frontend", "incident", "infra", "on-call", "pipeline", "runbook", "service", "svc", "vllm"],
  product: ["backlog", "feature", "launch", "product", "roadmap", "sprint", "ux"],
  legal: ["approval", "compliance", "contract", "legal", "privacy", "terms"],
  finance: ["billing", "budget", "discount", "finance", "invoice", "payment", "pricing", "refund", "revenue", "stripe"],
  hr: ["benefit", "employee", "headcount", "hire", "hr", "onboard", "payroll", "recruit"],
  sales: ["account", "acv", "ae", "arr", "commission", "deal", "deal desk", "discount", "enterprise", "quota", "sales", "salesforce", "smb", "svp", "vp sales"],
  marketing: ["campaign", "event", "lead", "marketing", "persona"],
  operations: ["approval", "escalation", "operations", "process", "sla", "workflow"],
  security: ["access", "auth", "credential", "incident", "policy", "security"],
  general: [],
};

const DEPARTMENT_LABELS: Record<Department, string> = {
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

function normalizeDepartment(value: unknown): Department {
  return typeof value === "string" && (DEPARTMENTS as readonly string[]).includes(value)
    ? value as Department
    : "general";
}

function sourceIdsForUnit(unit: Unit): string[] {
  return Array.from(new Set((unit.evidence ?? []).map((item) => item.sourceId).filter(Boolean) as string[]));
}

function unitText(unit: Unit): string {
  return `${unit.subject} ${unit.statement} ${(unit.entities ?? []).join(" ")}`.toLowerCase();
}

function departmentAnchorSet(units: Unit[], department: Department): Set<string> {
  const anchors = new Set<string>(DEPARTMENT_RELEVANCE_KEYWORDS[department].map((item) => item.toLowerCase()));
  for (const unit of units.filter((item) => normalizeDepartment(item.department) === department)) {
    anchors.add(subjectFor(unit).toLowerCase());
    for (const entity of unit.entities ?? []) anchors.add(entity.toLowerCase());
    for (const sourceId of sourceIdsForUnit(unit)) anchors.add(`source:${sourceId}`);
  }
  return anchors;
}

function isRelevantGeneralUnit(unit: Unit, department: Department, anchors: Set<string>): boolean {
  if (department === "general") return true;
  const text = unitText(unit);
  for (const sourceId of sourceIdsForUnit(unit)) {
    if (anchors.has(`source:${sourceId}`)) return true;
  }
  for (const anchor of anchors) {
    if (anchor.length >= 4 && text.includes(anchor)) return true;
  }
  return DEPARTMENT_RELEVANCE_KEYWORDS[department].some((keyword) => text.includes(keyword));
}

function activeUnits(state: State, department?: Department): Unit[] {
  const candidates = state.units.filter(
    (unit) => !unit.stale && !unit.supersededBy && unit.confidence >= MIN_SKILL_CONFIDENCE,
  );
  if (!department) return candidates;
  const anchors = departmentAnchorSet(candidates, department);
  return candidates.filter((unit) => {
    const unitDepartment = normalizeDepartment(unit.department);
    if (unitDepartment === department) return true;
    if (unitDepartment !== "general") return false;
    return isRelevantGeneralUnit(unit, department, anchors);
  });
}

function formatDate(value?: string): string {
  if (!value) return "unknown";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toISOString().slice(0, 10);
}

function escapeInline(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function cleanStatement(unit: Unit): string {
  const subject = escapeInline(unit.subject);
  let statement = escapeInline(unit.statement);
  if (!statement) return "";

  if (subject) {
    const prefix = new RegExp(`^${subject.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s+`, "i");
    statement = statement.replace(prefix, "");
  }
  statement = statement.replace(/^the\s+/i, "");
  return statement.charAt(0).toUpperCase() + statement.slice(1);
}

function subjectFor(unit: Unit): string {
  return escapeInline(unit.subject || unit.entities?.[0] || "General");
}

function confidenceRange(units: Unit[]): string {
  const values = units.map((unit) => unit.confidence).filter((n) => Number.isFinite(n));
  if (values.length === 0) return "unknown";
  const min = Math.min(...values).toFixed(2);
  const max = Math.max(...values).toFixed(2);
  return min === max ? min : `${min}-${max}`;
}

function aliasesFor(state: State, subject: string): string[] {
  const entity = state.entities.find((item) => item.name.toLowerCase() === subject.toLowerCase());
  return entity?.aliases?.filter(Boolean) ?? [];
}

function sourceIdsFor(units: Unit[]): string[] {
  const ids = new Set<string>();
  for (const unit of units) {
    for (const evidence of unit.evidence ?? []) {
      if (evidence.sourceId) ids.add(evidence.sourceId);
    }
  }
  return Array.from(ids);
}

function sourceMapFor(state: State): Map<string, State["sources"][number]> {
  return new Map(state.sources.map((source) => [source.id, source]));
}

function sourceLabel(state: State, sourceId?: string): string {
  if (!sourceId) return "unknown";
  const source = sourceMapFor(state).get(sourceId);
  return source ? `${source.id} (${source.title})` : sourceId;
}

function relatedEntitiesFor(units: Unit[], subject: string): string[] {
  const names = new Set<string>();
  for (const unit of units) {
    for (const entity of unit.entities ?? []) {
      if (entity.toLowerCase() !== subject.toLowerCase()) names.add(entity);
    }
  }
  return Array.from(names).sort((a, b) => a.localeCompare(b));
}

function latestUpdateFor(units: Unit[]): string {
  const timestamps = units
    .map((unit) => unit.updatedAt ?? unit.createdAt)
    .filter(Boolean)
    .map((value) => new Date(value).getTime())
    .filter((value) => Number.isFinite(value));
  if (timestamps.length === 0) return "unknown";
  return new Date(Math.max(...timestamps)).toISOString().slice(0, 10);
}

function temporalScopeFor(units: Unit[]): string {
  const statuses = new Set(units.map((unit) => unit.temporalStatus ?? "unknown"));
  if (statuses.size === 1) return Array.from(statuses)[0];
  if (statuses.has("future") || statuses.has("historical") || statuses.has("expired")) return "mixed";
  return "current";
}

function domainForUnits(units: Unit[]): string {
  const priority: UnitKind[] = ["policy", "process", "ownership", "gotcha", "decision", "definition", "fact"];
  for (const kind of priority) {
    const subjects = units
      .filter((unit) => unit.kind === kind)
      .map(subjectFor)
      .filter((subject) => subject !== "General");
    if (subjects.length > 0) return subjects[0];
  }
  return "Company Knowledge";
}

function quoteFor(unit: Unit): string | null {
  const quote = unit.evidence?.find((item) => item.quote)?.quote;
  return quote ? escapeInline(quote).slice(0, 220) : null;
}

// Returns the sector for a unit: trusts backend tag if set, else keyword-matches.
export function classifySector(unit: Unit): string {
  if (unit.sector && unit.sector !== "General") return unit.sector;
  const haystack = `${unit.subject} ${unit.statement}`.toLowerCase();
  for (const [sector, keywords] of Object.entries(SECTOR_KEYWORDS)) {
    if (keywords.some((kw) => haystack.includes(kw))) return sector;
  }
  return "General";
}

export function departmentCounts(state: State): Record<Department, number> {
  const counts = Object.fromEntries(DEPARTMENTS.map((department) => [department, 0])) as Record<Department, number>;
  for (const unit of state.units.filter((item) => !item.stale && !item.supersededBy)) {
    counts[normalizeDepartment(unit.department)] += 1;
  }
  return counts;
}

function renderStructuredUnit(state: State, unit: Unit): string[] {
  const firstSource = sourceIdsForUnit(unit)[0];
  const lines = [`- ${subjectFor(unit)}: ${cleanStatement(unit)}`];
  lines.push(`  - type: ${unit.kind}`);
  lines.push(`  - confidence: ${unit.confidence.toFixed(2)}`);
  lines.push(`  - temporal_status: ${unit.temporalStatus ?? "unknown"}`);
  lines.push(`  - effective_date: ${unit.effectiveDate ?? "null"}`);
  lines.push(`  - valid_from: ${unit.validFrom ?? "null"}`);
  lines.push(`  - valid_to: ${unit.validTo ?? "null"}`);
  lines.push(`  - updated_at: ${formatDate(unit.updatedAt ?? unit.createdAt)}`);
  lines.push(`  - source: ${sourceLabel(state, firstSource)}`);
  const quote = quoteFor(unit);
  if (quote) lines.push(`  - evidence: "${quote}"`);
  else lines.push("  - evidence: null");
  return lines;
}

function renderEntitySection(state: State, subject: string, units: Unit[]): string[] {
  const lines: string[] = [`### ${subject}`, ""];
  const aliases = aliasesFor(state, subject);
  const related = relatedEntitiesFor(units, subject);
  const sources = sourceIdsFor(units);

  lines.push("metadata:");
  lines.push(`  department: ${normalizeDepartment(units[0]?.department)}`);
  lines.push(`  sector: ${classifySector(units[0])}`);
  lines.push(`  aliases: ${aliases.length ? aliases.join(", ") : "none"}`);
  lines.push(`  related_entities: ${related.length ? related.join(", ") : "none"}`);
  lines.push(`  source_ids: ${sources.length ? sources.join(", ") : "unknown"}`);
  lines.push(`  confidence: ${confidenceRange(units)}`);
  lines.push(`  updated_at: ${latestUpdateFor(units)}`);
  const temporalStatuses = Array.from(new Set(units.map((unit) => unit.temporalStatus ?? "unknown")));
  lines.push(`  temporal_statuses: ${temporalStatuses.join(", ")}`);
  lines.push("");

  for (const kind of KIND_ORDER) {
    const byKind = units.filter((unit) => unit.kind === kind);
    if (byKind.length === 0) continue;
    lines.push(`#### ${KIND_LABELS[kind]}`);
    for (const unit of byKind) lines.push(...renderStructuredUnit(state, unit));
    lines.push("");
  }

  return lines;
}

function renderGroupedUnits(state: State, heading: string, units: Unit[]): string[] {
  if (units.length === 0) return [];
  const lines = [`## ${heading}`, ""];
  const bySubject = new Map<string, Unit[]>();
  for (const unit of units) {
    const subject = subjectFor(unit);
    const bucket = bySubject.get(subject) ?? [];
    bucket.push(unit);
    bySubject.set(subject, bucket);
  }

  for (const [subject, subjectUnits] of Array.from(bySubject.entries()).sort(([a], [b]) => a.localeCompare(b))) {
    lines.push(`### ${subject}`, "");
    for (const unit of subjectUnits.sort((a, b) => b.confidence - a.confidence)) {
      lines.push(...renderStructuredUnit(state, unit), "");
    }
  }
  return lines;
}

function renderCurrentOperationalFacts(state: State, units: Unit[]): string[] {
  const facts = units.filter((unit) => OPERATIONAL_KIND_ORDER.includes(unit.kind));
  return renderGroupedUnits(state, "Current Operational Facts", facts);
}

function renderTemporalNotes(state: State, units: Unit[]): string[] {
  const temporalUnits = units.filter((unit) =>
    Boolean(unit.validTo || unit.supersededAt || unit.pendingSupersedes?.length)
    || ["future", "historical", "expired"].includes(unit.temporalStatus ?? ""),
  );
  if (temporalUnits.length === 0) return [];

  const lines = ["## Temporal Notes", ""];
  for (const unit of temporalUnits.sort((a, b) => subjectFor(a).localeCompare(subjectFor(b)))) {
    const firstSource = sourceIdsForUnit(unit)[0];
    lines.push(`- ${subjectFor(unit)}: ${cleanStatement(unit)}`);
    lines.push(`  - current_state: ${unit.temporalStatus === "current" ? cleanStatement(unit) : "not current or unknown"}`);
    lines.push(`  - future_or_historical_state: ${unit.temporalStatus ?? "unknown"}`);
    lines.push(`  - effective_date: ${unit.effectiveDate ?? "null"}`);
    lines.push(`  - valid_from: ${unit.validFrom ?? "null"}`);
    lines.push(`  - valid_to: ${unit.validTo ?? "null"}`);
    lines.push(`  - superseded_at: ${unit.supersededAt ?? "null"}`);
    lines.push(`  - confidence: ${unit.confidence.toFixed(2)}`);
    lines.push(`  - source: ${sourceLabel(state, firstSource)}`);
  }
  lines.push("");
  return lines;
}

function agentRuleFor(unit: Unit): string | null {
  const statement = cleanStatement(unit);
  if (!statement || unit.confidence < 0.75) return null;
  if (unit.temporalStatus && ["expired", "historical"].includes(unit.temporalStatus)) return null;

  if (unit.kind === "policy") return `- Policy constraint: ${subjectFor(unit)} - ${statement}`;
  if (unit.kind === "process") return `- Follow process: ${subjectFor(unit)} - ${statement}`;
  if (unit.kind === "gotcha") return `- Check before acting: ${subjectFor(unit)} - ${statement}`;
  if (unit.kind === "ownership") return `- Route ownership questions for ${subjectFor(unit)} using this fact: ${statement}`;
  if (unit.kind === "decision") return `- Respect decision context for ${subjectFor(unit)}: ${statement}`;
  return null;
}

function renderAgentRules(units: Unit[]): string[] {
  const rules = Array.from(new Set(units.map(agentRuleFor).filter(Boolean) as string[])).slice(0, 30);
  const lines = ["## Agent Rules", ""];
  lines.push("- Use this skill as company-specific operational memory, not as general advice.");
  lines.push("- Prefer current facts over future, historical, expired, or unknown temporal facts.");
  lines.push("- Do not treat future effective dates as active before the effective date.");
  lines.push("- Do not invent owners, approvals, systems, dates, prices, customers, or incident causes.");
  lines.push("- If evidence is missing or confidence is low, say the brain does not have enough information.");
  if (rules.length > 0) lines.push(...rules);
  lines.push("");
  return lines;
}

function renderWhenToUse(department: Department | undefined, units: Unit[]): string[] {
  const kinds = new Set(units.map((unit) => unit.kind));
  const subjects = Array.from(new Set(units.map(subjectFor).filter((subject) => subject !== "General"))).slice(0, 8);
  const label = department ? DEPARTMENT_LABELS[department] : "company";
  const lines = ["## When To Use", "", "Use this skill when an agent needs to:"];
  lines.push(`- answer ${label.toLowerCase()} questions using BrainOS evidence`);
  if (subjects.length > 0) lines.push(`- reason about ${subjects.join(", ")}`);
  if (kinds.has("ownership")) lines.push("- route ownership, approval, escalation, or contact decisions");
  if (kinds.has("policy")) lines.push("- apply company policies as constraints before taking action");
  if (kinds.has("process")) lines.push("- follow operational workflows from source-backed process facts");
  if (kinds.has("gotcha")) lines.push("- avoid known operational gotchas before changing systems or processes");
  lines.push("");
  lines.push("Do not use this skill for:");
  lines.push("- facts outside the listed department/domain scope");
  lines.push("- claims not supported by a listed source or evidence quote");
  lines.push("- treating historical, expired, or future facts as current");
  lines.push("");
  return lines;
}

function renderScope(state: State, department: Department | undefined, units: Unit[]): string[] {
  const deptLabel = department ? DEPARTMENT_LABELS[department] : "All departments";
  const subjects = Array.from(new Set(units.map(subjectFor).filter(Boolean))).slice(0, 16);
  const lines = ["## Scope", ""];
  lines.push(`- department: ${department ?? "all"}`);
  lines.push(`- domain: ${domainForUnits(units)}`);
  lines.push("- applies_to:");
  for (const subject of subjects.length ? subjects : ["General"]) lines.push(`  - ${subject}`);
  lines.push(`- temporal_scope: ${temporalScopeFor(units)}`);
  lines.push(`- generated_at: ${new Date().toISOString()}`);
  lines.push(`- source_count: ${sourceIdsFor(units).length || state.sources.length}`);
  lines.push(`- label: ${deptLabel}`);
  lines.push("");
  return lines;
}

function renderSourceIndex(state: State, units: Unit[]): string[] {
  const ids = sourceIdsFor(units);
  if (ids.length === 0) return [];
  const sources = sourceMapFor(state);
  const lines = ["## Source Index", ""];
  for (const id of ids.sort()) {
    const source = sources.get(id);
    if (!source) {
      lines.push(`- ${id}: unknown`);
      continue;
    }
    lines.push(`- ${source.id}: ${source.title}, ${formatDate(source.capturedAt)}, ${source.kind}`);
  }
  lines.push("");
  return lines;
}

function renderRelationships(state: State, units: Unit[]): string[] {
  const unitIds = new Set(units.map((unit) => unit.id));
  const relationships = (state.relationships ?? []).filter(
    (rel) => !rel.unitId || unitIds.has(rel.unitId),
  );
  if (relationships.length === 0) return [];

  const lines = ["## Knowledge Graph Relationships", ""];
  for (const rel of relationships.slice(0, 120)) {
    const metadata = [
      rel.id ? `id:${rel.id}` : "",
      rel.sourceId ? `source:${rel.sourceId}` : "",
      `confidence:${rel.confidence.toFixed(2)}`,
    ].filter(Boolean).join(" | ");
    lines.push(`- ${rel.from} --${rel.relation}--> ${rel.to} <!-- ${metadata} -->`);
  }
  lines.push("");
  return lines;
}

// Render the Code Map section. Only emitted if at least one code source has
// been ingested. Stays terse so it doesn't crowd out the operational facts.
function renderCodeMap(state: State): string[] {
  const codeSources = state.sources.filter((s) => s.kind === "code" && s.codebase);
  if (codeSources.length === 0) return [];

  const lines: string[] = ["## Code Map", ""];

  for (const src of codeSources) {
    const cb = src.codebase!;
    const langs = Object.entries(cb.byLanguage)
      .slice(0, 6)
      .map(([k, v]) => `${k}:${v}`)
      .join(", ");
    const dirs = Object.entries(cb.topLevelDirs)
      .slice(0, 8)
      .map(([k, v]) => `${k} (${v})`)
      .join(", ");

    lines.push(`### ${src.title}`);
    lines.push(
      `- captured: ${src.capturedAt}`,
      `- files: ${cb.totalFiles}${cb.truncated ? " (truncated)" : ""}`,
      `- languages: ${langs}`,
      `- top-level dirs: ${dirs}`,
    );
    if (cb.rationaleFilesExtracted != null) {
      lines.push(`- rationale files extracted: ${cb.rationaleFilesExtracted}`);
    }
    lines.push("");

    // Entity ↔ Path links — the bridge that lets the agent jump from a fact
    // (e.g. "billing service was migrated") to the actual code location.
    const ep = cb.entityPaths ?? {};
    const epEntries = Object.entries(ep).slice(0, 40);
    if (epEntries.length > 0) {
      lines.push("**Entity → Path**", "");
      for (const [entity, paths] of epEntries) {
        const shown = paths.slice(0, 4).join(", ") +
          (paths.length > 4 ? `, … (+${paths.length - 4} more)` : "");
        lines.push(`- \`${entity}\` → ${shown}`);
      }
      lines.push("");
    }

    // Module summaries — LLM-generated "what this directory does" overviews.
    // Useful as cheap orientation for an agent dropped into an unfamiliar repo.
    const modules = cb.moduleSummaries ?? [];
    if (modules.length > 0) {
      lines.push("**Modules**", "");
      for (const m of modules) {
        lines.push(`- \`${m.dir}/\` (${m.fileCount} files) — ${m.summary}`);
      }
      lines.push("");
    }

    // Top symbols — first ~30 by name. Lets the agent answer "where is X
    // defined?" without re-reading code.
    const sIndex = cb.symbolIndex ?? {};
    const sEntries = Object.entries(sIndex).slice(0, 30);
    if (sEntries.length > 0) {
      lines.push("**Top symbols → path**", "");
      for (const [name, occ] of sEntries) {
        const first = occ[0];
        const more = occ.length > 1 ? ` (+${occ.length - 1} more defs)` : "";
        lines.push(`- \`${name}\` (${first.kind}) — ${first.path}:${first.line}${more}`);
      }
      lines.push("");
    }

    // Import-graph hubs — files imported-by many others. Strong "central
    // module" signal for the agent.
    const ig = cb.importGraph;
    if (ig && ig.stats.internalEdges > 0) {
      const hubs = ig.stats.hubs.slice(0, 8);
      lines.push(
        `- import edges: ${ig.stats.internalEdges} internal · ${ig.stats.externalDeps} external deps`,
      );
      if (hubs.length > 0) {
        lines.push("**Import hubs (fan-in)**", "");
        for (const h of hubs) {
          lines.push(`- ${h.path} ← ${h.fanIn}`);
        }
        lines.push("");
      }
    }

    // Call-graph top callees — collapses (caller, callee) edges into "this
    // function is called N times across the codebase".
    const calls = cb.callEdges ?? [];
    if (calls.length > 0) {
      const counts: Record<string, number> = {};
      for (const c of calls) counts[c.callee] = (counts[c.callee] ?? 0) + 1;
      const top = Object.entries(counts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10);
      lines.push("**Top callees**", "");
      for (const [name, n] of top) {
        lines.push(`- \`${name}\` — ${n}×`);
      }
      lines.push("");
    }
  }

  return lines;
}

export function generateSkills(state: State, department?: Department): string {
  const units = activeUnits(state, department);
  if (units.length === 0) return "# Skill: Company Knowledge Memory\n\nNo knowledge ingested yet.\n";

  const scope = department
    ? `${DEPARTMENT_LABELS[department]}${department === "general" ? "" : " + General"}`
    : "All departments";
  const title = department
    ? `# Skill: ${DEPARTMENT_LABELS[department]} ${domainForUnits(units)} Memory`
    : "# Skill: Company Knowledge Memory";

  const lines: string[] = [
    title,
    "",
    "Generated by BrainOS as compact, source-backed operational memory for agents.",
    "",
    "metadata:",
    "  skill_version: 4",
    `  generated_at: ${new Date().toISOString()}`,
    `  scope: ${scope}`,
    `  retrieval_mode: hybrid_bm25_vector_graph`,
    `  units: ${units.length}`,
    `  entities: ${state.entities.length}`,
    `  sources: ${state.sources.length}`,
    `  temporal_scope: ${temporalScopeFor(units)}`,
    "",
  ];

  lines.push(...renderScope(state, department, units));
  lines.push(...renderWhenToUse(department, units));

  const departments = department
    ? department === "general"
      ? ["general" as Department]
      : [department, "general" as Department]
    : DEPARTMENTS;

  for (const dept of departments) {
    const deptUnits = units.filter((unit) => normalizeDepartment(unit.department) === dept);
    if (deptUnits.length === 0) continue;

    if (!department) lines.push(`# ${DEPARTMENT_LABELS[dept]} Department Skill`, "");
    lines.push(...renderCurrentOperationalFacts(state, deptUnits));
    lines.push(...renderGroupedUnits(state, "Ownership And Routing", deptUnits.filter((unit) => unit.kind === "ownership")));
    lines.push(...renderGroupedUnits(state, "Policies", deptUnits.filter((unit) => unit.kind === "policy")));
    lines.push(...renderGroupedUnits(state, "Processes", deptUnits.filter((unit) => unit.kind === "process")));
    lines.push(...renderGroupedUnits(state, "Gotchas", deptUnits.filter((unit) => unit.kind === "gotcha")));
    lines.push(...renderGroupedUnits(state, "Decisions", deptUnits.filter((unit) => unit.kind === "decision")));
    lines.push(...renderTemporalNotes(state, deptUnits));
  }

  lines.push(...renderAgentRules(units));
  lines.push(...renderRelationships(state, units));
  lines.push(...renderCodeMap(state));
  lines.push(...renderSourceIndex(state, units));
  return lines.join("\n").trimEnd() + "\n";
}

export function generateSkillsJSON(state: State, department?: Department) {
  const units = activeUnits(state, department);
  return {
    version: 4,
    generatedAt: new Date().toISOString(),
    department: department ?? "all",
    retrievalMode: "hybrid_bm25_vector_graph",
    temporalScope: temporalScopeFor(units),
    totalUnits: units.length,
    totalEntities: state.entities.length,
    totalSources: state.sources.length,
    scope: {
      department: department ?? "all",
      domain: units.length ? domainForUnits(units) : "Company Knowledge",
      appliesTo: Array.from(new Set(units.map(subjectFor).filter(Boolean))),
      temporalScope: temporalScopeFor(units),
    },
    agentRules: Array.from(new Set(units.map(agentRuleFor).filter(Boolean) as string[])),
    units: units.map((unit) => ({
      id: unit.id,
      kind: unit.kind,
      department: normalizeDepartment(unit.department),
      sector: classifySector(unit),
      subject: unit.subject,
      statement: unit.statement,
      confidence: unit.confidence,
      updatedAt: unit.updatedAt ?? unit.createdAt,
      validFrom: unit.validFrom ?? null,
      validTo: unit.validTo ?? null,
      effectiveDate: unit.effectiveDate ?? null,
      observedAt: unit.observedAt ?? null,
      supersededAt: unit.supersededAt ?? null,
      temporalStatus: unit.temporalStatus ?? "unknown",
      entities: unit.entities ?? [],
      evidence: unit.evidence ?? [],
      sourceIds: sourceIdsForUnit(unit),
    })),
    relationships: state.relationships ?? [],
    entities: state.entities,
    sources: state.sources,
  };
}
