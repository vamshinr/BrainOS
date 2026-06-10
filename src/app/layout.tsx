import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AppShell } from "@/components/app-shell";
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
    "Causal memory engine for AI agents. Stores timestamped events and directed cause→effect edges, then answers \"why did X happen?\" by walking the causal graph back to root cause and forward to consequences.",
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
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
