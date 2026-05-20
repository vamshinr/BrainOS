import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const includeClosed = url.searchParams.get("include_closed") === "true";

  try {
    const res = await fetch(
      `${BACKEND_URL}/api/decision-alerts?include_closed=${includeClosed ? "true" : "false"}`,
      { cache: "no-store" },
    );
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { alerts: [], error: "Decision alerts unavailable", detail: String(e) },
      { status: 502 },
    );
  }
}
