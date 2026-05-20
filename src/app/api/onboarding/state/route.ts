import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/onboarding/state`, {
      cache: "no-store",
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Backend returned ${res.status}: ${txt}`);
    }
    return NextResponse.json(await res.json());
  } catch (e) {
    // Fail open: assume not onboarded so the wizard shows. Better UX than a
    // blank page when the backend is briefly down.
    return NextResponse.json(
      {
        docsReady: false,
        slackReady: false,
        docsCount: 0,
        slackChannels: [],
        slackConfigured: false,
        completedAt: null,
        complete: false,
        error: String(e),
      },
      { status: 200 },
    );
  }
}
