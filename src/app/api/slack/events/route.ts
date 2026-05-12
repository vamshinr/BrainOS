import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 300;

export async function POST(req: Request) {
  const body = await req.text();

  try {
    const backendRes = await fetch(`${BACKEND_URL}/api/slack/events`, {
      method: "POST",
      headers: {
        "Content-Type": req.headers.get("content-type") ?? "application/json",
        "X-Slack-Request-Timestamp": req.headers.get("x-slack-request-timestamp") ?? "",
        "X-Slack-Signature": req.headers.get("x-slack-signature") ?? "",
      },
      body,
    });

    const text = await backendRes.text();
    return new NextResponse(text, {
      status: backendRes.status,
      headers: {
        "Content-Type": backendRes.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (e) {
    console.error("Slack events proxy failed:", e);
    return NextResponse.json({ error: "Slack events proxy failed", detail: String(e) }, { status: 500 });
  }
}
