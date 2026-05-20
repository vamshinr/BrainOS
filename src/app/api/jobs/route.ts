import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/jobs`, { cache: "no-store" });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { active: null, queued: [], recent: [], error: String(e) },
      { status: 502 },
    );
  }
}
