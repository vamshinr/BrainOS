"use client";

import { Nav } from "@/components/nav";

/**
 * Top-level shell: sidebar nav + main content.
 *
 * The legacy global widgets (job-queue dock, decision-alert popover, onboarding
 * gate) were removed together with the legacy backend — Mnemosyne ingests
 * synchronously and has no job queue or alert stream.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="md:grid md:min-h-screen md:grid-cols-[240px_1fr]">
      <Nav />
      <main className="min-w-0 pb-24">{children}</main>
    </div>
  );
}
