import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET() {
  try {
    const backendRes = await fetch(`${BACKEND_URL}/api/slack/health`, {
      cache: "no-store",
    });
    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }
    return NextResponse.json(await backendRes.json());
  } catch (e) {
    return NextResponse.json({ error: "Slack health failed", detail: String(e) }, { status: 500 });
  }
}

