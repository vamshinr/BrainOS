import { BACKEND_URL } from "@/lib/backend";
import { unstable_cache } from "next/cache";
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

export interface Source {
  id: string;
  title: string;
  kind: string;
  capturedAt: string;
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

const CACHE_TAG = "brain-state";
const BACKEND = BACKEND_URL;

async function fetchState(): Promise<State> {
  try {
    const res = await fetch(`${BACKEND}/api/state`, {
      next: { tags: [CACHE_TAG] },
    });
    if (!res.ok) throw new Error(`Backend ${res.status}`);
    return res.json();
  } catch {
    return { units: [], sources: [], entities: [], rawChunks: [] };
  }
}

export const readState = unstable_cache(fetchState, ["brain-state"]);

export function invalidateCache() {
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
