// Types for the Mnemosyne causal memory engine responses, and the thin client
// the UI uses. The Next.js /api/* routes are the adapter; pages call those.

export interface MnemEvent {
  id: string;
  summary: string;
  detail?: string;
  occurred_at: string;
  learned_at?: string;
  tags: string[];
  source_id?: string;
  reinforcement_count?: number;
  salience?: number;
}

export interface MnemEdge {
  id: string;
  cause_id: string;
  effect_id: string;
  relation: string; // "caused" | "triggered" | "led_to" | "enabled" | ...
  confidence: number;
  evidence?: string;
  method?: string;
  occurred_delta_s?: number;
}

export interface GraphDump {
  events: MnemEvent[];
  edges: MnemEdge[];
}

// ── /ingest ──────────────────────────────────────────────────────────────────
export interface IngestResult {
  events_created: string[];
  events_reinforced: { event_id: string; reinforcement_count: number }[];
  edges_created: MnemEdge[];
  counts: { created: number; reinforced: number; edges: number };
}

// ── /retrieve (causal) ───────────────────────────────────────────────────────
export interface ChainEntry {
  event: MnemEvent;
  incoming_relation: string | null;
  confidence: number | null;
}

export interface CausalResult {
  mode: "causal";
  query: string;
  anchor_event_id: string | null;
  chain: ChainEntry[];
  answer: string;
  excluded_distractors: string[];
}

// ── /retrieve (associative) ──────────────────────────────────────────────────
export interface AssociativeChunk {
  id: string;
  score: number;
  event: MnemEvent | null;
  payload?: Record<string, unknown> | null;
}

export interface AssociativeResult {
  mode: "associative";
  query: string;
  chunks: AssociativeChunk[];
}

export type RetrieveResult = CausalResult | AssociativeResult;

export const RELATION_COLORS: Record<string, string> = {
  caused: "#ef4444",
  triggered: "#f97316",
  led_to: "#eab308",
  enabled: "#22c55e",
  supersedes: "#8b5cf6",
};

export function relationColor(relation?: string | null): string {
  return (relation && RELATION_COLORS[relation]) || "#64748b";
}
