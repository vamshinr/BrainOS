import { BACKEND_URL } from "@/lib/backend";
import { revalidatePath } from "next/cache";
import type { UnitKind, EntityKind, Department, TemporalStatus } from "./types";

export interface Unit {
  id: string;
  statement: string;
  subject: string;
  kind: UnitKind;
  confidence: number;
  createdAt: string;
  updatedAt?: string;
  entities: string[];
  department?: Department;
  evidence?: { sourceId?: string; quote?: string }[];
  validFrom?: string;
  validTo?: string;
  effectiveDate?: string;
  observedAt?: string;
  supersededAt?: string;
  temporalStatus?: TemporalStatus;
  pendingSupersedes?: string[];
  stale?: boolean;
  supersededBy?: string;
  sector?: string;
  disputed?: boolean;
  conflictsWith?: string[];
}

export interface FileSymbol {
  name: string;
  kind: string; // "class" | "function" | "method" | "type" | "interface" | "const" | "enum" | "struct" | "trait" | "impl"
  line: number;
  async?: boolean;
  bases?: string[];
  children?: FileSymbol[];
}

export interface FileOutline {
  imports: string[];
  exports: string[];
  symbols: FileSymbol[];
  _skipped?: string;
  _error?: string;
}

export interface CodebaseFile {
  path: string;
  size: number;
  category: string;
  language: string;
  outline?: FileOutline;
}

export interface SymbolOccurrence {
  path: string;
  kind: string;
  line: number;
  parent?: string;
}

export interface ImportEdge {
  from: string;
  to: string;
  kind: string;
}

export interface ImportGraph {
  edges: ImportEdge[];
  external: Record<string, number>;
  stats: {
    internalEdges: number;
    externalDeps: number;
    hubs: { path: string; fanIn: number }[];
  };
}

export interface CallEdge {
  from: string;
  fromFunc: string;
  to: string;
  callee: string;
  line: number;
  confidence: number;
  ambiguous: boolean;
}

export interface ModuleSummary {
  dir: string;
  fileCount: number;
  languages: Record<string, number>;
  summary: string;
}

export interface CodebaseSummary {
  totalFiles: number;
  truncated?: boolean;
  byLanguage: Record<string, number>;
  byCategory: Record<string, number>;
  topLevelDirs: Record<string, number>;
  rationaleFilesExtracted?: number;
  outlinesBuilt?: number;
  files?: CodebaseFile[];
  entityPaths?: Record<string, string[]>;
  symbolIndex?: Record<string, SymbolOccurrence[]>;
  importGraph?: ImportGraph;
  callEdges?: CallEdge[];
  moduleSummaries?: ModuleSummary[];
}

export interface Source {
  id: string;
  title: string;
  kind: string;
  capturedAt: string;
  // Present when kind === "code" — the map produced by /api/ingest_code.
  codebase?: CodebaseSummary;
}

export interface Entity {
  name: string;
  kind: EntityKind;
  aliases?: string[];
}

export interface RawChunk {
  id: string;
  sourceId: string;
  sourceTitle?: string;
  kind?: string;
  chunkIndex: number;
  text: string;
  charCount: number;
  createdAt?: string;
}

export interface State {
  units: Unit[];
  sources: Source[];
  entities: Entity[];
  rawChunks?: RawChunk[];
  relationships?: {
    id?: string;
    from: string;
    relation: string;
    to: string;
    unitId?: string;
    sourceId?: string;
    confidence: number;
    createdAt?: string;
  }[];
}

const BACKEND = BACKEND_URL;

// Read brain state directly from the Python backend on every call. We
// deliberately don't cache here — brain.json lives on the same VM as the
// backend, the fetch is microseconds, and caching introduced a live-refresh
// bug after job-queue ingest where the home page would show stale Recent
// Knowledge until a hard reload. Force-dynamic pages already prevent route
// segment caching; this keeps the data layer fresh too.
export async function readState(): Promise<State> {
  try {
    const res = await fetch(`${BACKEND}/api/state`, { cache: "no-store" });
    if (!res.ok) throw new Error(`Backend ${res.status}`);
    return res.json();
  } catch {
    return { units: [], sources: [], entities: [], rawChunks: [] };
  }
}

export function invalidateCache() {
  // No data-layer cache to bust, but we still revalidate the route segment
  // so any client components subscribed to it pick up the fresh render.
  revalidatePath("/", "layout");
}

export async function clearAll(): Promise<State> {
  invalidateCache();
  return { units: [], sources: [], entities: [], rawChunks: [] };
}

export async function deleteUnit(unitId: string): Promise<State> {
  try {
    await fetch(`${BACKEND}/api/units/${unitId}`, { method: "DELETE" });
  } catch {
    // best-effort
  }
  invalidateCache();
  return readState();
}
