// Pure rule-based detector for agent thrashing. Runs in the browser / Next.js
// server with no LLM, no backend hop. Output feeds the failure synthesizer,
// which then ships a narrative to the existing /api/ingest pipeline.

export type ThrashRule = "tool_call_repeat" | "apply_revert" | "same_error_retry";

export interface TraceEvent {
  index: number;
  tool: string;
  args: string;        // serialized; used for similarity
  filePath?: string;   // best-effort, only for Edit/Write/Read
  ok: boolean;
  error?: string;
  raw: string;         // original line / chunk, for evidence quoting
}

export interface ThrashEpisode {
  rule: ThrashRule;
  tool?: string;
  occurrences: number;
  filePath?: string;
  errorSignature?: string;
  events: TraceEvent[];
  summary: string;
  evidenceQuote: string;
}

// ── Parsing ─────────────────────────────────────────────────────────────────

// Accepts three shapes:
//   1. Claude Code / Cursor JSONL — one JSON object per line, tool_use blocks
//      in assistant messages paired with tool_result blocks in later user
//      messages via tool_use_id.
//   2. JSON array of {tool, args, ok, error}  (or {name, input, error})
//   3. Free-form text — best-effort extraction of tool calls + errors.
export function parseTrace(input: string): TraceEvent[] {
  const trimmed = input.trim();
  if (!trimmed) return [];

  // JSONL: ≥2 non-empty lines and ≥80% of them start with `{`.
  const lines = trimmed.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  if (lines.length >= 2) {
    const jsonish = lines.filter((l) => l.startsWith("{")).length;
    if (jsonish / lines.length >= 0.8) {
      const events = parseClaudeCodeJsonl(lines);
      if (events.length > 0) return events;
    }
  }

  // Try JSON first.
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed);
      const arr: unknown[] = Array.isArray(parsed) ? parsed : [parsed];
      const events: TraceEvent[] = [];
      arr.forEach((raw, i) => {
        if (!raw || typeof raw !== "object") return;
        const obj = raw as Record<string, unknown>;
        const tool =
          (obj.tool as string) ??
          (obj.name as string) ??
          (obj.tool_name as string) ??
          "unknown";
        const argsObj = obj.args ?? obj.input ?? obj.parameters ?? obj.params ?? {};
        const args = typeof argsObj === "string" ? argsObj : JSON.stringify(argsObj);
        const error =
          (obj.error as string) ??
          (obj.error_message as string) ??
          (typeof obj.result === "string" && /error|fail/i.test(obj.result) ? (obj.result as string) : undefined);
        const explicitOk = typeof obj.ok === "boolean" ? (obj.ok as boolean) : undefined;
        const ok = explicitOk ?? !error;
        const filePath =
          (typeof argsObj === "object" && argsObj !== null
            ? ((argsObj as Record<string, unknown>).file_path as string) ??
              ((argsObj as Record<string, unknown>).path as string) ??
              ((argsObj as Record<string, unknown>).file as string)
            : undefined) ?? undefined;
        events.push({
          index: i,
          tool: String(tool),
          args,
          filePath,
          ok,
          error,
          raw: JSON.stringify(obj),
        });
      });
      return events;
    } catch {
      // fall through to text parse
    }
  }

  return parseTextTrace(trimmed);
}

// Claude Code transcript adapter. Each line is one JSON record; tool_use
// blocks live in assistant message content, and their outcome lands in a
// later user message as a tool_result block keyed by tool_use_id. We pair
// them so ev.ok / ev.error reflect the actual result.
function parseClaudeCodeJsonl(lines: string[]): TraceEvent[] {
  const events: TraceEvent[] = [];
  const byId = new Map<string, TraceEvent>();
  let counter = 0;

  for (const line of lines) {
    if (!line.startsWith("{")) continue;
    let obj: Record<string, unknown>;
    try {
      obj = JSON.parse(line) as Record<string, unknown>;
    } catch {
      continue;
    }
    const msg = obj.message as Record<string, unknown> | undefined;
    const content = msg?.content;
    if (!Array.isArray(content)) continue;

    for (const blockRaw of content) {
      if (!blockRaw || typeof blockRaw !== "object") continue;
      const block = blockRaw as Record<string, unknown>;
      const blockType = block.type as string | undefined;

      if (blockType === "tool_use") {
        const id = typeof block.id === "string" ? block.id : "";
        const tool = typeof block.name === "string" ? block.name : "unknown";
        const input = block.input ?? {};
        const args = typeof input === "string" ? input : JSON.stringify(input);
        const inputObj = typeof input === "object" && input !== null ? (input as Record<string, unknown>) : null;
        const filePath = inputObj
          ? (inputObj.file_path as string) ?? (inputObj.path as string) ?? (inputObj.file as string) ?? undefined
          : undefined;
        const ev: TraceEvent = {
          index: counter++,
          tool,
          args,
          filePath,
          ok: true, // optimistic; flipped when we see a matching tool_result
          raw: line.slice(0, 1000),
        };
        events.push(ev);
        if (id) byId.set(id, ev);
        continue;
      }

      if (blockType === "tool_result") {
        const id = typeof block.tool_use_id === "string" ? block.tool_use_id : "";
        const ev = id ? byId.get(id) : undefined;
        if (!ev) continue;
        const isError = block.is_error === true;
        let resultText = "";
        const result = block.content;
        if (typeof result === "string") {
          resultText = result;
        } else if (Array.isArray(result)) {
          resultText = result
            .map((c) => {
              if (typeof c === "string") return c;
              if (c && typeof c === "object") {
                const t = (c as Record<string, unknown>).text;
                return typeof t === "string" ? t : "";
              }
              return "";
            })
            .join("\n");
        }
        if (isError) {
          ev.ok = false;
          ev.error = (resultText || "tool_result is_error").slice(0, 500);
        }
        continue;
      }
    }
  }

  return events;
}

// Heuristic text parser — looks for common Claude Code / Cursor patterns:
//   "Bash(command: npm run build)"
//   "Edit(file_path: src/foo.ts, ...)"
//   "Error: ..."
function parseTextTrace(text: string): TraceEvent[] {
  const events: TraceEvent[] = [];
  const lines = text.split(/\r?\n/);
  const toolCallRe =
    /^\s*([A-Z][A-Za-z]+)\s*\(([^)]*)\)\s*$|^\s*\[?tool\]?\s*[:=]\s*([A-Za-z_][\w]*)\s*(?:args?\s*[:=]\s*(.*))?$/;
  const errorRe = /(?:^|\s)(error|exception|failed|failure|stderr)[:\s]/i;
  const pathRe = /(?:file_path|path|file)\s*[:=]\s*['"]?([^,'")\s]+)/i;

  let pending: TraceEvent | null = null;
  let counter = 0;

  const flush = () => {
    if (pending) {
      events.push(pending);
      pending = null;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;

    const m = line.match(toolCallRe);
    if (m) {
      flush();
      const tool = m[1] ?? m[3] ?? "unknown";
      const args = (m[2] ?? m[4] ?? "").trim();
      const pathMatch = args.match(pathRe);
      pending = {
        index: counter++,
        tool,
        args,
        filePath: pathMatch ? pathMatch[1] : undefined,
        ok: true,
        raw: line,
      };
      continue;
    }

    if (pending && errorRe.test(line)) {
      pending.ok = false;
      pending.error = line.replace(/^[^A-Za-z]*(error|exception|failed|failure|stderr)[:\s]*/i, "").trim() || line;
      pending.raw += "\n" + line;
      continue;
    }

    if (pending && line.length < 400) {
      pending.raw += "\n" + line;
    }
  }
  flush();

  return events;
}

// ── Normalization helpers ───────────────────────────────────────────────────

function normalizeError(err: string | undefined): string {
  if (!err) return "";
  return err
    .replace(/\s+/g, " ")
    .replace(/\b\/[\w./-]+/g, "<path>")           // absolute paths
    .replace(/(?:^|\s)[\w./-]+\.(?:ts|tsx|js|jsx|py|go|rs|java|md|json|yaml|yml)\b/gi, " <file>")
    .replace(/\b0x[0-9a-f]+\b/gi, "<hex>")
    .replace(/\b\d{2,}\b/g, "<n>")
    .replace(/line\s*<n>/gi, "line <n>")
    .trim()
    .toLowerCase()
    .slice(0, 200);
}

function similarity(a: string, b: string): number {
  if (a === b) return 1;
  if (!a || !b) return 0;
  const longer = a.length >= b.length ? a : b;
  const shorter = a.length < b.length ? a : b;
  if (longer.length === 0) return 1;
  // Cheap Jaccard on character trigrams — Levenshtein is overkill for args
  // strings that may be long.
  const tri = (s: string) => {
    const set = new Set<string>();
    for (let i = 0; i < s.length - 2; i++) set.add(s.slice(i, i + 3));
    return set;
  };
  const A = tri(longer);
  const B = tri(shorter);
  let inter = 0;
  for (const t of B) if (A.has(t)) inter++;
  const union = A.size + B.size - inter;
  return union === 0 ? 0 : inter / union;
}

// ── Detectors ───────────────────────────────────────────────────────────────

const MIN_REPEATS = 3;
const ARG_SIM_THRESHOLD = 0.85;

function detectToolCallRepeat(events: TraceEvent[]): ThrashEpisode[] {
  const byTool = new Map<string, TraceEvent[]>();
  for (const ev of events) {
    if (ev.ok) continue;
    const arr = byTool.get(ev.tool) ?? [];
    arr.push(ev);
    byTool.set(ev.tool, arr);
  }

  const episodes: ThrashEpisode[] = [];
  for (const [tool, evs] of byTool) {
    if (evs.length < MIN_REPEATS) continue;
    // Cluster by arg similarity.
    const used = new Set<number>();
    for (let i = 0; i < evs.length; i++) {
      if (used.has(i)) continue;
      const cluster: TraceEvent[] = [evs[i]];
      used.add(i);
      for (let j = i + 1; j < evs.length; j++) {
        if (used.has(j)) continue;
        if (similarity(evs[i].args, evs[j].args) >= ARG_SIM_THRESHOLD) {
          cluster.push(evs[j]);
          used.add(j);
        }
      }
      if (cluster.length >= MIN_REPEATS) {
        episodes.push({
          rule: "tool_call_repeat",
          tool,
          occurrences: cluster.length,
          events: cluster,
          summary: `Agent retried \`${tool}\` ${cluster.length}× with near-identical args, all failing.`,
          evidenceQuote: cluster[0].raw.slice(0, 220),
        });
      }
    }
  }
  return episodes;
}

function detectApplyRevert(events: TraceEvent[]): ThrashEpisode[] {
  // For each file path, look at the args sequence of edits — if a later args
  // string matches an earlier one we have an apply-revert ping-pong.
  const byPath = new Map<string, TraceEvent[]>();
  for (const ev of events) {
    if (!ev.filePath) continue;
    if (!/edit|write/i.test(ev.tool)) continue;
    const arr = byPath.get(ev.filePath) ?? [];
    arr.push(ev);
    byPath.set(ev.filePath, arr);
  }

  const episodes: ThrashEpisode[] = [];
  for (const [path, evs] of byPath) {
    if (evs.length < 3) continue;
    const seen = new Map<string, number>();
    let revertCount = 0;
    for (const ev of evs) {
      const key = normalizeError(ev.args).slice(0, 120) || ev.args.slice(0, 120);
      const prior = seen.get(key);
      if (prior !== undefined && prior < evs.indexOf(ev) - 1) revertCount++;
      seen.set(key, evs.indexOf(ev));
    }
    if (revertCount >= 1 && evs.length >= 3) {
      episodes.push({
        rule: "apply_revert",
        filePath: path,
        occurrences: evs.length,
        events: evs,
        summary: `Agent edited \`${path}\` ${evs.length}× and reverted to a prior version at least once.`,
        evidenceQuote: evs[0].raw.slice(0, 220),
      });
    }
  }
  return episodes;
}

function detectSameErrorRetry(events: TraceEvent[]): ThrashEpisode[] {
  const byError = new Map<string, TraceEvent[]>();
  for (const ev of events) {
    if (ev.ok || !ev.error) continue;
    const sig = normalizeError(ev.error);
    if (!sig) continue;
    const arr = byError.get(sig) ?? [];
    arr.push(ev);
    byError.set(sig, arr);
  }

  const episodes: ThrashEpisode[] = [];
  for (const [sig, evs] of byError) {
    if (evs.length < MIN_REPEATS) continue;
    episodes.push({
      rule: "same_error_retry",
      tool: evs[0].tool,
      errorSignature: sig,
      occurrences: evs.length,
      events: evs,
      summary: `Agent hit the same error ${evs.length}× across calls: "${sig.slice(0, 100)}".`,
      evidenceQuote: (evs[0].error ?? evs[0].raw).slice(0, 220),
    });
  }
  return episodes;
}

export function detectThrashing(events: TraceEvent[]): ThrashEpisode[] {
  if (events.length === 0) return [];
  const all = [
    ...detectToolCallRepeat(events),
    ...detectApplyRevert(events),
    ...detectSameErrorRetry(events),
  ];

  // De-duplicate near-identical episodes by (rule, tool, filePath, errorSig).
  const seen = new Set<string>();
  const out: ThrashEpisode[] = [];
  for (const ep of all) {
    const key = `${ep.rule}|${ep.tool ?? ""}|${ep.filePath ?? ""}|${ep.errorSignature ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(ep);
  }
  out.sort((a, b) => b.occurrences - a.occurrences);
  return out;
}

// Turn one or more episodes into a narrative the existing ingest pipeline
// can extract a gotcha unit from. The "[agent-trap]" prefix is the marker
// used downstream by skills.ts to surface a dedicated Known Agent Traps
// section in SKILLS.md.
export function synthesizeNarrative(
  episodes: ThrashEpisode[],
  repoLabel?: string,
): { title: string; content: string } {
  if (episodes.length === 0) {
    return {
      title: "[agent-trap] (empty)",
      content: "No thrash episodes detected.",
    };
  }
  const headline = episodes[0];
  const repo = repoLabel ? ` in ${repoLabel}` : "";
  const title = `[agent-trap] ${prettyRule(headline.rule)} on ${
    headline.tool ?? headline.filePath ?? "unknown"
  }${repo}`;

  const lines: string[] = [];
  lines.push(
    `Agent execution trace${repo} surfaced ${episodes.length} thrash episode${
      episodes.length > 1 ? "s" : ""
    }. Each is a durable trap future agents should avoid before retrying.`,
    "",
  );

  for (const ep of episodes) {
    lines.push(`## ${prettyRule(ep.rule)} (${ep.occurrences}×)`);
    lines.push(ep.summary);
    if (ep.tool) lines.push(`- Failing tool: \`${ep.tool}\``);
    if (ep.filePath) lines.push(`- Failing file: \`${ep.filePath}\``);
    if (ep.errorSignature) lines.push(`- Normalized error: ${ep.errorSignature}`);
    lines.push(`- Evidence (first event): "${ep.evidenceQuote.replace(/"/g, "'")}"`);

    const sampleArgs = ep.events
      .slice(0, 3)
      .map((e) => `  - ${e.tool}(${e.args.slice(0, 160)})${e.error ? ` → ${e.error.slice(0, 120)}` : ""}`)
      .join("\n");
    lines.push("- Sample calls:");
    lines.push(sampleArgs);
    lines.push("");
  }

  lines.push(
    "Lesson: a future agent operating on this repo must treat the above as a known trap. Before retrying any of the failing tool calls listed, the agent should re-read the file context, surface the durable error to the user, or escalate, rather than re-running the same command with a minor variation. This is a gotcha — not advisory.",
  );

  return { title, content: lines.join("\n") };
}

function prettyRule(rule: ThrashRule): string {
  switch (rule) {
    case "tool_call_repeat":
      return "Repeated failing tool-call";
    case "apply_revert":
      return "Apply-then-revert loop";
    case "same_error_retry":
      return "Same-error retry loop";
  }
}
