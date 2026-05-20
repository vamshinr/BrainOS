import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function POST() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/onboarding/complete`, {
      method: "POST",
    });
    return NextResponse.json(await res.json(), { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { error: "Failed to mark onboarding complete", detail: String(e) },
      { status: 502 },
    );
  }
}
