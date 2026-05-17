import { NextResponse } from "next/server";
// import { BACKEND_URL } from "@/lib/backend";

export const runtime = "nodejs";

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ session_id: string }> }
) {
  void _req;
  void (await params);

  // BrainOS Agent feature is kept in the codebase, but session clearing is disabled.
  // const { session_id } = await params;
  // try {
  //   await fetch(`${BACKEND_URL}/api/agent/session/${session_id}`, { method: "DELETE" });
  // } catch {
  //   // best-effort
  // }
  // return NextResponse.json({ ok: true });

  return NextResponse.json({ error: "BrainOS Agent feature is disabled" }, { status: 404 });
}
