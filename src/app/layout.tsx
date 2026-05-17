import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Nav } from "@/components/nav";
import { QueueDock } from "@/components/queue-dock";
import { DecisionAlertPopover } from "@/components/decision-alert-popover";
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
  icons: {
    icon: [{ url: "/brainos-icon.svg", type: "image/svg+xml" }],
    shortcut: ["/brainos-icon.svg"],
    apple: [{ url: "/brainos-icon.svg", type: "image/svg+xml" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

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
        <div className="md:grid md:min-h-screen md:grid-cols-[240px_1fr]">
          <Nav />
          <main className="min-w-0 pb-24">{children}</main>
        </div>
        <DecisionAlertPopover />
        <QueueDock />
      </body>
    </html>
  );
}
