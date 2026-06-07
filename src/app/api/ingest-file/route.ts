import { BACKEND_URL } from "@/lib/backend";
import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 60;

// Mnemosyne ingests raw text only. We read text files server-side and forward
// the contents to /ingest. PDF/DOC parsing is intentionally not supported.
const TEXT_EXTS = /\.(txt|md|markdown|csv|log|json)$/i;

export async function POST(req: Request) {
  const contentType = req.headers.get("content-type") ?? "";
  if (!contentType.includes("multipart/form-data")) {
    return NextResponse.json({ error: "Expected multipart/form-data" }, { status: 400 });
  }

  try {
    const formData = await req.formData();
    const file = formData.get("file") as File | null;
    const title = formData.get("title") as string | null;

    if (!file) {
      return NextResponse.json({ error: "file is required" }, { status: 400 });
    }
    if (!TEXT_EXTS.test(file.name) && !file.type.startsWith("text/")) {
      return NextResponse.json(
        { error: "Mnemosyne ingests text only — upload .txt, .md, .csv, .log, or .json (PDF/DOC not supported)." },
        { status: 415 },
      );
    }

    const text = await file.text();
    if (!text.trim()) {
      return NextResponse.json({ error: "File is empty" }, { status: 400 });
    }

    const res = await fetch(`${BACKEND_URL}/api/jobs/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        source_id: title ?? file.name,
        title: title ?? file.name,
        kind: "ingest_file",
      }),
    });
    if (!res.ok) {
      throw new Error(`Mnemosyne ${res.status}: ${await res.text()}`);
    }
    return NextResponse.json(await res.json()); // { job_id }
  } catch (e) {
    console.error("File ingest error:", e);
    return NextResponse.json({ error: "File ingest failed", detail: String(e) }, { status: 500 });
  }
}
