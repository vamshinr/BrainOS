import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// Onboarding is legacy "company brain" UI; the Mnemosyne backend implements no
// /api/onboarding/* endpoints, so proxying there only produced 404s on every poll.
// Report "complete" statically (no backend call) so the app loads straight to the
// dashboard. The wizard pages are kept but no longer block or poll the backend.
export async function GET() {
  return NextResponse.json({
    docsReady: true,
    slackReady: true,
    docsCount: 0,
    slackChannels: [],
    slackConfigured: false,
    completedAt: null,
    complete: true,
  });
}
