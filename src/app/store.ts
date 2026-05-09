import { UnitKind } from "./types";

export interface Unit {
  id: string;
  statement: string;
  subject: string;
  kind: UnitKind;
  confidence: number;
  createdAt: string;
  stale?: boolean;
  supersededBy?: string;
}

export interface Source {
  id: string;
  title: string;
  kind: string;
  capturedAt: string;
}

export interface State {
  units: Unit[];
  sources: Source[];
  entities: any[];
}

export async function readState(): Promise<State> {
  // This is a placeholder - you'll need to implement actual state reading
  return {
    units: [],
    sources: [],
    entities: []
  };
}
