"use client";

import { usePathname } from "next/navigation";
import { Nav } from "@/components/nav";
import { QueueDock } from "@/components/queue-dock";
import { DecisionAlertPopover } from "@/components/decision-alert-popover";
import { OnboardingGate } from "@/components/onboarding-gate";

/**
 * Top-level shell. Two layouts:
 *   - /welcome: full-bleed wizard, no chrome
 *   - everything else: gated app with sidebar nav + dock + decision-alert popover
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/";

  if (pathname.startsWith("/welcome")) {
    return <OnboardingGate>{children}</OnboardingGate>;
  }

  return (
    <OnboardingGate>
      <div className="md:grid md:min-h-screen md:grid-cols-[240px_1fr]">
        <Nav />
        <main className="min-w-0 pb-24">{children}</main>
      </div>
      <DecisionAlertPopover />
      <QueueDock />
    </OnboardingGate>
  );
}
