import { NextResponse } from "next/server";
import { readState } from "@/lib/store";
import { generateSkills, generateSkillsJSON } from "@/lib/skills";
import { DEPARTMENTS, type Department } from "@/lib/types";

export const runtime = "nodejs";

export async function GET(req: Request) {
  const url = new URL(req.url);
  const format = url.searchParams.get("format") ?? "md";
  const deptParam = url.searchParams.get("department");

  let department: Department | undefined;
  if (deptParam && (DEPARTMENTS as string[]).includes(deptParam)) {
    department = deptParam as Department;
  }

  const state = await readState();

  if (format === "json") {
    return NextResponse.json(generateSkillsJSON(state, department));
  }

  const md = generateSkills(state, department);
  const filename = department ? `SKILLS-${department}.md` : "SKILLS.md";
  return new NextResponse(md, {
    status: 200,
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Content-Disposition": `inline; filename="${filename}"`,
    },
  });
}
