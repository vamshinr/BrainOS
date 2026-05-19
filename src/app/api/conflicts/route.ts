import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/conflicts`, { cache: "no-store" });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`Backend ${res.status}: ${errText}`);
    }
    return NextResponse.json(await res.json());
  } catch (e) {
    return NextResponse.json(
      { error: "Failed to load conflicts", detail: String(e) },
      { status: 500 },
    );
  }
}
