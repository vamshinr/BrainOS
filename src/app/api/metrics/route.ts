import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET() {
  try {
    const res = await fetch("http://localhost:8081/api/metrics", {
      next: { revalidate: 0 },
    });
    if (!res.ok) throw new Error(`Backend ${res.status}`);
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { error: "Metrics backend unavailable", detail: String(e) },
      { status: 503 },
    );
  }
}
