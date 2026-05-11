import { NextResponse } from "next/server";
import { invalidateCache } from "@/lib/store";

export const runtime = "nodejs";
export const maxDuration = 300;

const ALLOWED_TYPES = new Set([
  "application/pdf",
  "text/plain",
  "text/markdown",
  "text/csv",
  "application/msword",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/octet-stream", // fallback for .md files on some OS
]);

const ALLOWED_EXTS = /\.(pdf|txt|md|csv|doc|docx)$/i;

export async function POST(req: Request) {
  const contentType = req.headers.get("content-type") ?? "";
  if (!contentType.includes("multipart/form-data")) {
    return NextResponse.json({ error: "Expected multipart/form-data" }, { status: 400 });
  }

  try {
    const formData = await req.formData();
    const file = formData.get("file") as File | null;
    const title = formData.get("title") as string | null;
    const kind = (formData.get("kind") as string | null) ?? "doc";
    const url = formData.get("url") as string | null;
    const model = formData.get("model") as string | null;

    if (!file) {
      return NextResponse.json({ error: "file is required" }, { status: 400 });
    }

    const ext = file.name.match(ALLOWED_EXTS);
    if (!ext && !ALLOWED_TYPES.has(file.type)) {
      return NextResponse.json(
        { error: "Unsupported file type. Upload PDF, DOC, DOCX, TXT, MD, or CSV." },
        { status: 415 },
      );
    }

    const backendFormData = new FormData();
    backendFormData.append("file", file, file.name);
    if (title) backendFormData.append("title", title);
    backendFormData.append("kind", kind);
    if (url) backendFormData.append("url", url);
    if (model) backendFormData.append("model", model);

    const backendRes = await fetch(`${BACKEND_URL}/api/ingest_file", {
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
      charsExtracted: data.chars_extracted ?? 0,
      fallbackExtraction: data.fallback_extraction ?? false,
      totals,
    });
  } catch (e) {
    console.error("File Ingest Error:", e);
    return NextResponse.json({ error: "File ingest failed", detail: String(e) }, { status: 500 });
  }
}
