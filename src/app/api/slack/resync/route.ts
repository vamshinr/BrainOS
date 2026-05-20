import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 120;

export async function POST(req: Request) {
  try {
    const url = new URL(req.url);
    const limit = url.searchParams.get("limit") || "50";
    const res = await fetch(
      `${BACKEND_URL}/api/slack/resync?limit=${encodeURIComponent(limit)}`,
      { method: "POST" },
    );
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { error: "Slack resync failed", detail: String(e) },
      { status: 502 },
    );
  }
}
