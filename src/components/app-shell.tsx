"use client";

import { Nav } from "@/components/nav";
import { QueueDock } from "@/components/queue-dock";

/**
 * Top-level shell: sidebar nav + main content + the async-ingestion queue dock
 * (bottom-right), which streams job progress from the backend over SSE.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="md:grid md:min-h-screen md:grid-cols-[240px_1fr]">
      <Nav />
      <main className="min-w-0 pb-24">{children}</main>
      <QueueDock />
    </div>
  );
}
