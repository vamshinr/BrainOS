import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  try {
    const res = await fetch(
      `${BACKEND_URL}/api/decision-alerts/${encodeURIComponent(id)}/ack`,
      { method: "POST" },
    );
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { error: "Decision alert acknowledge failed", detail: String(e) },
      { status: 502 },
    );
  }
}
