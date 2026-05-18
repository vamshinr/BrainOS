"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/theme-toggle";

type NavItem = { href: string; label: string; hint: string };

const BASE_NAV: NavItem[] = [
  { href: "/", label: "Brain", hint: "Overview" },
  // BrainOS Agent feature is kept in the codebase, but hidden from navigation.
  // { href: "/agent", label: "Agent", hint: "Autonomous AI · Gemma 4" },
  { href: "/ingest", label: "Ingest", hint: "Capture knowledge" },
  { href: "/failures", label: "Traps", hint: "Loop memory" },
  { href: "/graph", label: "Map", hint: "Entities & links" },
  { href: "/code", label: "Code", hint: "Codebase map · ownership · ADRs" },
  { href: "/ask", label: "Ask", hint: "Query the brain" },
  { href: "/skills", label: "Skills", hint: "Export for agents" },
  { href: "/slack", label: "Slack", hint: "MCP integration" },
  { href: "/metrics", label: "GPU", hint: "AMD MI300X live stats" },
];

const ONBOARD_NAV: NavItem = {
  href: "/welcome",
  label: "Onboard",
  hint: "Customer setup wizard",
};

export function Nav() {
  const [open, setOpen] = useState(false);
  const [onboarded, setOnboarded] = useState<boolean | null>(null);
  const pathname = usePathname();

  // Poll the onboarding state so the "Onboard" tab disappears once the user
  // finishes the wizard, and reappears if they reset it via Settings.
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch("/api/onboarding/state", { cache: "no-store" })
        .then((r) => r.json())
        .then((d) => {
          if (!cancelled) setOnboarded(!!d.complete);
        })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 10_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  useEffect(() => {
    queueMicrotask(() => setOpen(false));
  }, [pathname]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open]);

  // Build the visible nav: hide "Onboard" once onboarding is complete.
  // Default to hiding during initial load to avoid a flash for completed users.
  const navItems: NavItem[] = onboarded === false ? [BASE_NAV[0], ONBOARD_NAV, ...BASE_NAV.slice(1)] : BASE_NAV;

  return (
    <>
      {/* Mobile top bar */}
      <header className="md:hidden sticky top-0 z-30 flex items-center justify-between border-b border-[var(--border)] bg-[var(--background)]/95 backdrop-blur px-4 h-14">
        <Link href="/" className="flex items-center gap-2">
          <div className="size-7 rounded-md bg-[var(--accent)] grid place-items-center text-white text-xs font-bold">
            CB
          </div>
          <span className="font-semibold">Brain OS</span>
        </Link>
        <button
          type="button"
          aria-label="Open menu"
          aria-expanded={open}
          onClick={() => setOpen(true)}
          className="rounded-md p-2 hover:bg-[var(--card)] transition-colors"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
      </header>

      {/* Mobile drawer */}
      {open && (
        <div className="md:hidden fixed inset-0 z-40">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <aside className="absolute left-0 top-0 h-full w-72 max-w-[85vw] bg-[var(--background)] border-r border-[var(--border)] px-5 py-5 overflow-y-auto shadow-xl">
            <div className="flex items-center justify-between mb-6">
              <Link href="/" className="flex items-center gap-2">
                <div className="size-7 rounded-md bg-[var(--accent)] grid place-items-center text-white text-xs font-bold">
                  CB
                </div>
                <span className="font-semibold">Brain OS</span>
              </Link>
              <button
                type="button"
                aria-label="Close menu"
                onClick={() => setOpen(false)}
                className="rounded-md p-1.5 hover:bg-[var(--card)] transition-colors"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            <NavList pathname={pathname} items={navItems} />
            <div className="mt-6 pt-6 border-t border-[var(--border)]">
              <ThemeToggle />
            </div>
          </aside>
        </div>
      )}

      {/* Desktop sidebar */}
      <aside className="hidden md:block border-r border-[var(--border)] bg-[var(--muted)]/40 px-5 py-6 sticky top-0 h-screen">
        <Link href="/" className="block">
          <div className="flex items-center gap-2">
            <div className="size-7 rounded-md bg-[var(--accent)] grid place-items-center text-white text-xs font-bold">
              CB
            </div>
            <div>
              <div className="font-semibold leading-none">Brain OS</div>
              <div className="text-[11px] text-[var(--muted-foreground)] mt-0.5">
                Memory for AI agents
              </div>
            </div>
          </div>
        </Link>

        <nav className="mt-8 flex flex-col gap-1">
          <NavList pathname={pathname} items={navItems} />
        </nav>

        <div className="absolute bottom-6 left-5 right-5 space-y-4">
          <ThemeToggle />
          <p className="text-[11px] text-[var(--muted-foreground)] leading-relaxed">
            Atomic facts, reconciled when things change, served to your agents
            with provenance on every claim.
          </p>
        </div>
      </aside>
    </>
  );
}

function NavList({
  pathname,
  items,
}: {
  pathname: string;
  items: NavItem[];
}) {
  return (
    <nav className="flex flex-col gap-1">
      {items.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`rounded-md px-3 py-2 transition-colors ${
              active
                ? "bg-[var(--card)] border border-[var(--border)]"
                : "hover:bg-[var(--background)]"
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
  );
}
