import { NextResponse } from "next/server";
// import { BACKEND_URL } from "@/lib/backend";
// import { z } from "zod";

export const runtime = "nodejs";
export const maxDuration = 300;

// BrainOS Agent feature is kept in the codebase, but the API proxy is disabled.
// const Body = z.object({
//   session_id: z.string().optional(),
//   message: z.string().min(1),
// });

export async function POST(req: Request) {
  void req;

  // let body: z.infer<typeof Body>;
  // try {
  //   body = Body.parse(await req.json());
  // } catch (e) {
  //   return NextResponse.json({ error: "Invalid body", detail: String(e) }, { status: 400 });
  // }
  //
  // try {
  //   const backendRes = await fetch(`${BACKEND_URL}/api/agent`, {
  //     method: "POST",
  //     headers: { "Content-Type": "application/json" },
  //     body: JSON.stringify({ session_id: body.session_id, message: body.message }),
  //   });
  //
  //   if (!backendRes.ok) {
  //     const errText = await backendRes.text();
  //     throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
  //   }
  //
  //   const data = await backendRes.json();
  //   return NextResponse.json(data);
  // } catch (e) {
  //   console.error("[Agent API] Error:", e);
  //   return NextResponse.json(
  //     { error: "Agent backend failed", detail: String(e) },
  //     { status: 500 }
  //   );
  // }

  return NextResponse.json({ error: "BrainOS Agent feature is disabled" }, { status: 404 });
}
