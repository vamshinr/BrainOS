import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

// Destructive: clears all events + edges from Neo4j + Qdrant via Mnemosyne.
export async function POST() {
  try {
    const res = await fetch(`${BACKEND_URL}/reset`, { method: "POST" });
    if (!res.ok) throw new Error(`Mnemosyne ${res.status}: ${await res.text()}`);
    return NextResponse.json(await res.json());
  } catch (e) {
    console.error("Reset error:", e);
    return NextResponse.json({ error: "Reset failed", detail: String(e) }, { status: 500 });
  }
}
