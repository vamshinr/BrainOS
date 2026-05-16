import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ session_id: string }> }
) {
  const { session_id } = await params;
  try {
    await fetch(`${BACKEND_URL}/api/agent/session/${session_id}`, { method: "DELETE" });
  } catch {
    // best-effort
  }
  return NextResponse.json({ ok: true });
}
