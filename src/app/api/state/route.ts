import { NextResponse } from "next/server";
import { readState, clearAll, deleteUnit, invalidateCache } from "@/lib/store";

export const runtime = "nodejs";

export async function GET() {
  const state = await readState();
  return NextResponse.json(state);
}

export async function DELETE(req: Request) {
  const url = new URL(req.url);
  const unitId = url.searchParams.get("unit");

  if (unitId) {
    // Remove from ChromaDB first so the vector doesn't linger in semantic search
    try {
      await fetch(`${BACKEND_URL}/api/units/${encodeURIComponent(unitId)}`, {
        method: "DELETE",
      });
    } catch {
      // Backend may be down — still remove from brain.json
    }
    const next = await deleteUnit(unitId);
    invalidateCache();
    return NextResponse.json({ ok: true, units: next.units.length });
  }

  if (url.searchParams.get("all") === "true") {
    // Clear Python backend first — wipes ChromaDB collection and brain.json
    try {
      const backendRes = await fetch(`${BACKEND_URL}/api/clear`, {
        method: "DELETE",
      });
      if (!backendRes.ok) {
        const errText = await backendRes.text();
        console.warn("Backend clear failed:", errText);
      }
    } catch (e) {
      // Backend may be down; fall through to clear brain.json locally
      console.warn("Could not reach backend for clear:", e);
    }

    // Also clear via the store so the Next.js cache and brain.json are in sync
    // even if the Python backend was unreachable above.
    await clearAll();
    invalidateCache();

    return NextResponse.json({ ok: true, cleared: true });
  }

  return NextResponse.json(
    { error: "specify ?unit=<id> or ?all=true" },
    { status: 400 },
  );
}
