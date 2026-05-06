import { NextResponse } from "next/server";
import { readState } from "@/lib/store";
import { generateSkills, generateSkillsJSON } from "@/lib/skills";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const format = url.searchParams.get("format") ?? "md";
  const state = await readState();
  if (format === "json") {
    return NextResponse.json(generateSkillsJSON(state));
  }
  const md = generateSkills(state);
  return new NextResponse(md, {
    status: 200,
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Content-Disposition": 'inline; filename="SKILLS.md"',
    },
  });
}
