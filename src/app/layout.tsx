import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import { ThemeToggle } from "@/components/theme-toggle";
import { QueueDock } from "@/components/queue-dock";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Brain OS",
  description:
    "Reconciled memory infrastructure for AI agents. Extracts atomic, attributable facts from Slack, email, tickets and docs; supersedes them when things change; serves them to your agents with provenance on every claim.",
};

const NAV: { href: string; label: string; hint: string }[] = [
  { href: "/", label: "Brain", hint: "Overview" },
  { href: "/ingest", label: "Ingest", hint: "Capture knowledge" },
  { href: "/graph", label: "Map", hint: "Entities & links" },
  { href: "/ask", label: "Ask", hint: "Query the brain" },
  { href: "/skills", label: "Skills", hint: "Export for agents" },
  { href: "/slack", label: "Slack", hint: "MCP integration" },
  { href: "/metrics", label: "GPU", hint: "AMD MI300X live stats" },
];

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const themeScript = `
    (() => {
      try {
        const stored = localStorage.getItem("brain-os-theme");
        const theme = stored === "light" || stored === "dark"
          ? stored
          : (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
        document.documentElement.classList.toggle("dark", theme === "dark");
        document.documentElement.classList.toggle("light", theme === "light");
        document.documentElement.style.colorScheme = theme;
      } catch {}
    })();
  `;

  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full">
        <div className="grid min-h-screen grid-cols-[240px_1fr]">
          <aside className="border-r border-[var(--border)] bg-[var(--muted)]/40 px-5 py-6 sticky top-0 h-screen">
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
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="group rounded-md px-3 py-2 hover:bg-[var(--background)] transition-colors"
                >
                  <div className="text-sm font-medium">{item.label}</div>
                  <div className="text-[11px] text-[var(--muted-foreground)]">
                    {item.hint}
                  </div>
                </Link>
              ))}
            </nav>

            <div className="absolute bottom-6 left-5 right-5 space-y-4">
              <ThemeToggle />
              <p className="text-[11px] text-[var(--muted-foreground)] leading-relaxed">
                Atomic facts, reconciled when things change, served to your
                agents with provenance on every claim.
              </p>
            </div>
          </aside>

          <main className="min-w-0 pb-24">{children}</main>
        </div>
        <QueueDock />
      </body>
    </html>
  );
}
