import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET() {
  try {
    const res = await fetch("http://localhost:8081/api/models", { cache: "no-store" });
    if (!res.ok) throw new Error(`Backend ${res.status}`);
    return NextResponse.json(await res.json());
  } catch (e) {
    return NextResponse.json(
      { models: [], defaults: { text: "", vlm: "" }, error: String(e) },
      { status: 200 }, // soft-fail so the UI still renders without a picker
    );
  }
}
