import { NextResponse } from "next/server";

export const runtime = "nodejs";

const BACKEND = process.env.PYTHON_BACKEND_URL || "http://localhost:8081";

async function proxy(req: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  const target = `${BACKEND}/api/slack/${path.join("/")}`;
  const init: RequestInit = {
    method: req.method,
    headers: { "Content-Type": "application/json" },
  };
  if (req.method !== "GET" && req.method !== "DELETE" && req.method !== "HEAD") {
    init.body = await req.text();
  }
  const upstream = await fetch(target, init);
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("Content-Type") ?? "application/json" },
  });
}

export const GET = proxy;
export const POST = proxy;
export const DELETE = proxy;
