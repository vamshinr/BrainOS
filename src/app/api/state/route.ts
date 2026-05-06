import { NextResponse } from "next/server";
import { readState, clearAll, deleteUnit } from "@/lib/store";

export const runtime = "nodejs";

export async function GET() {
  const state = await readState();
  return NextResponse.json(state);
}

export async function DELETE(req: Request) {
  const url = new URL(req.url);
  const unitId = url.searchParams.get("unit");
  if (unitId) {
    const next = await deleteUnit(unitId);
    return NextResponse.json({ ok: true, units: next.units.length });
  }
  if (url.searchParams.get("all") === "true") {
    await clearAll();
    return NextResponse.json({ ok: true, cleared: true });
  }
  return NextResponse.json({ error: "specify ?unit=<id> or ?all=true" }, { status: 400 });
}
