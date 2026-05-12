import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function POST() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/analyze/gaps`, {
      method: "POST",
    });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`Backend ${res.status}: ${errText}`);
    }
    return NextResponse.json(await res.json());
  } catch (e) {
    return NextResponse.json(
      { error: "Gap analysis failed", detail: String(e) },
      { status: 500 },
    );
  }
}
