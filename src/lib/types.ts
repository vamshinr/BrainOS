export type UnitKind =
  | "fact"
  | "process"
  | "decision"
  | "ownership"
  | "definition"
  | "policy"
  | "gotcha";

export const DEPARTMENTS = [
  "engineering",
  "product",
  "legal",
  "finance",
  "hr",
  "sales",
  "marketing",
  "operations",
  "security",
  "general",
] as const;

export type Department = (typeof DEPARTMENTS)[number];

export type TemporalStatus =
  | "current"
  | "future"
  | "expired"
  | "historical"
  | "unknown";

export type EntityKind =
  | "person"
  | "team"
  | "system"
  | "product"
  | "process"
  | "concept"
  | "tool"
  | "customer";

export type Sector =
  | "HR"
  | "Legal"
  | "Finance"
  | "Engineering"
  | "Product"
  | "Supply Chain"
  | "General";
