"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

type State = {
  complete: boolean;
  docsReady: boolean;
  slackReady: boolean;
  completedAt: string | null;
};

const ALWAYS_ALLOWED_PREFIXES = [
  "/welcome",   // the wizard itself
  "/_next",
  "/api",       // server routes (the gate is for pages, not APIs)
  "/favicon",
];

/**
 * Top-level client gate. Reads `/api/onboarding/state` once on mount, then
 * routes the user to `/welcome` if they haven't finished onboarding, or
 * lets them through if they have. Pages outside the customer flow (anything
 * under the dev-only nav) inherit the same gate.
 */
export function OnboardingGate({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";
  const router = useRouter();
  const [decided, setDecided] = useState(false);
  const [shouldRender, setShouldRender] = useState(false);

  const isAlwaysAllowed = ALWAYS_ALLOWED_PREFIXES.some((p) =>
    pathname.startsWith(p),
  );

  useEffect(() => {
    let cancelled = false;
    if (isAlwaysAllowed) {
      setDecided(true);
      setShouldRender(true);
      return;
    }
    fetch("/api/onboarding/state", { cache: "no-store" })
      .then((r) => r.json() as Promise<State>)
      .then((s) => {
        if (cancelled) return;
        if (!s.complete) {
          router.replace("/welcome");
          setDecided(true);
          // don't render children; we're navigating away
        } else {
          setDecided(true);
          setShouldRender(true);
        }
      })
      .catch(() => {
        // Backend down — fail closed and send them to the wizard. The wizard
        // page surfaces backend errors clearly so they can debug.
        if (cancelled) return;
        router.replace("/welcome");
        setDecided(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isAlwaysAllowed, router]);

  if (!decided) {
    return <FullscreenSplash />;
  }
  if (!shouldRender) {
    return <FullscreenSplash />;
  }
  return <>{children}</>;
}

function FullscreenSplash() {
  return (
    <div className="min-h-screen grid place-items-center bg-[var(--background)]">
      <div className="flex items-center gap-3 text-[var(--muted-foreground)]">
        <span className="size-1.5 rounded-full bg-[var(--accent)] animate-pulse" />
        <span className="text-xs uppercase tracking-widest">Loading workspace</span>
      </div>
    </div>
  );
}
