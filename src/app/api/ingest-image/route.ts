import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 60;

export async function POST(req: Request) {
  const contentType = req.headers.get("content-type") ?? "";
  if (!contentType.includes("multipart/form-data")) {
    return NextResponse.json({ error: "Expected multipart/form-data" }, { status: 400 });
  }

  try {
    const formData = await req.formData();
    const backendFormData = new FormData();

    const file = formData.get("file") as File | null;
    const title = formData.get("title") as string | null;
    const kind = (formData.get("kind") as string | null) ?? "doc";
    const url = formData.get("url") as string | null;
    const model = formData.get("model") as string | null;
    const textModel = formData.get("text_model") as string | null;

    if (!file) {
      return NextResponse.json({ error: "file is required" }, { status: 400 });
    }

    backendFormData.append("file", file, file.name);
    if (title) backendFormData.append("title", title);
    backendFormData.append("kind", kind);
    if (url) backendFormData.append("url", url);
    if (model) backendFormData.append("model", model);
    if (textModel) backendFormData.append("text_model", textModel);

    const backendRes = await fetch(`${BACKEND_URL}/api/ingest_image`, {
      method: "POST",
      body: backendFormData,
    });

    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }

    // Pass the enqueue response through. See /api/ingest/route.ts for why.
    const data = await backendRes.json();
    return NextResponse.json(data, { status: backendRes.status });
  } catch (e) {
    console.error("Image enqueue error:", e);
    return NextResponse.json({ error: "Backend failed to enqueue image", detail: String(e) }, { status: 500 });
  }
}
