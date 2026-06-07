import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

// Dump the causal graph (events + cause->effect edges) for the map view.
export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/graph`, { cache: "no-store" });
    if (!res.ok) throw new Error(`Mnemosyne ${res.status}`);
    return NextResponse.json(await res.json());
  } catch (e) {
    // Degrade gracefully so the map renders empty instead of erroring.
    return NextResponse.json({ events: [], edges: [], error: String(e) });
  }
}
