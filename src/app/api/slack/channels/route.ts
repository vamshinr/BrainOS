import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const query = url.searchParams.get("query") ?? "";
  try {
    const backendRes = await fetch(
      `http://localhost:8081/api/slack/list_channels?query=${encodeURIComponent(query)}`,
      { cache: "no-store" },
    );
    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }
    return NextResponse.json(await backendRes.json());
  } catch (e) {
    return NextResponse.json(
      { error: "Slack channel listing failed", detail: String(e) },
      { status: 500 },
    );
  }
}
