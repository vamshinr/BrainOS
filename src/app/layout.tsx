import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
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
    "A living map of how a company actually works — extracted from Slack, email, tickets, docs, and meetings into executable knowledge for AI agents.",
};

const NAV: { href: string; label: string; hint: string }[] = [
  { href: "/", label: "Brain", hint: "Overview" },
  { href: "/ingest", label: "Ingest", hint: "Capture knowledge" },
  { href: "/graph", label: "Map", hint: "Entities & links" },
  { href: "/ask", label: "Ask", hint: "Query the brain" },
  { href: "/skills", label: "Skills", hint: "Export for agents" },
];

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
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

            <div className="absolute bottom-6 left-5 right-5 text-[11px] text-[var(--muted-foreground)] leading-relaxed">
              Pull knowledge from every fragmented source. Structure it. Keep it
              current. Ship it as a skill file.
            </div>
          </aside>

          <main className="min-w-0">{children}</main>
        </div>
      </body>
    </html>
  );
}
