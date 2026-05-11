import { NextResponse } from "next/server";
import { invalidateCache } from "@/lib/store";

export const runtime = "nodejs";
export const maxDuration = 300;

export async function POST(req: Request) {
  const contentType = req.headers.get("content-type") ?? "";
  if (!contentType.includes("multipart/form-data")) {
    return NextResponse.json({ error: "Expected multipart/form-data" }, { status: 400 });
  }

  try {
    // Forward the multipart body directly to the Python backend
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

    const backendRes = await fetch(`${BACKEND_URL}/api/ingest_image", {
      method: "POST",
      body: backendFormData,
    });

    if (!backendRes.ok) {
      const errText = await backendRes.text();
      throw new Error(`Backend returned ${backendRes.status}: ${errText}`);
    }

    const data = await backendRes.json();
    invalidateCache();

    const totals = data.brain_totals ?? { sources: 1, entities: 0, units: data.units_stored ?? 0 };

    return NextResponse.json({
      sourceId: data.source_id,
      addedUnits: data.units_stored ?? 0,
      addedEntities: data.entities_stored ?? 0,
      addedRelationships: data.relationships_stored ?? 0,
      supersededUnits: data.units_superseded ?? 0,
      vlmDescriptionChars: data.vlm_description_chars ?? 0,
      fallbackExtraction: data.fallback_extraction ?? false,
      totals,
    });
  } catch (e) {
    console.error("Image Ingest Error:", e);
    return NextResponse.json({ error: "Image ingest failed", detail: String(e) }, { status: 500 });
  }
}
