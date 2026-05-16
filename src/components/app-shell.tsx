"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/theme-toggle";

const NAV: { href: string; label: string; hint: string }[] = [
  { href: "/", label: "Brain", hint: "Overview" },
  { href: "/ingest", label: "Ingest", hint: "Capture knowledge" },
  { href: "/graph", label: "Map", hint: "Entities & links" },
  { href: "/ask", label: "Ask", hint: "Query the brain" },
  { href: "/skills", label: "Skills", hint: "Export for agents" },
  { href: "/slack", label: "Slack", hint: "MCP integration" },
  { href: "/metrics", label: "GPU", hint: "AMD MI300X live stats" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const isOnboarding = pathname?.startsWith("/onboarding") ?? false;

  if (isOnboarding) {
    return <main className="min-h-screen">{children}</main>;
  }

  return (
    <div className="grid min-h-screen grid-cols-[240px_1fr]">
      <aside className="border-r border-[var(--border)] bg-[var(--muted)]/40 px-5 py-6 sticky top-0 h-screen">
        <Link href="/" className="block">
          <div className="flex items-center gap-2">
            <div className="size-7 rounded-md bg-[var(--accent)] grid place-items-center text-white text-xs font-bold">
              CB
            </div>
            <div>
              <div className="font-semibold leading-none">Company Brain</div>
              <div className="text-[11px] text-[var(--muted-foreground)] mt-0.5">
                The layer agents need
              </div>
            </div>
          </div>
        </Link>

        <nav className="mt-8 flex flex-col gap-1">
          {NAV.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname?.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`group rounded-md px-3 py-2 transition-colors ${
                  active ? "bg-[var(--background)]" : "hover:bg-[var(--background)]"
                }`}
              >
                <div className="text-sm font-medium">{item.label}</div>
                <div className="text-[11px] text-[var(--muted-foreground)]">
                  {item.hint}
                </div>
              </Link>
            );
          })}
        </nav>

        <div className="absolute bottom-6 left-5 right-5 space-y-4">
          <Link
            href="/onboarding"
            className="block text-[11px] text-[var(--muted-foreground)] hover:text-[var(--foreground)] underline underline-offset-2"
          >
            Run setup again →
          </Link>
          <ThemeToggle />
          <p className="text-[11px] text-[var(--muted-foreground)] leading-relaxed">
            Pull knowledge from every fragmented source. Structure it. Keep it
            current. Ship it as a skill file.
          </p>
        </div>
      </aside>

      <main className="min-w-0">{children}</main>
    </div>
  );
}
