"use client";

import { useState } from "react";

export function ResetButton() {
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);

  async function reset() {
    setLoading(true);
    try {
      await fetch("/api/state?all=true", { method: "DELETE" });
      // Hard navigate instead of router.refresh() — router.refresh() only
      // invalidates the current route's RSC payload; other pages (/graph,
      // /skills) keep serving stale router-cache entries until a full reload.
      window.location.href = "/";
    } catch {
      setLoading(false);
      setConfirming(false);
    }
  }

  if (confirming) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-[var(--muted-foreground)]">Wipe everything?</span>
        <button
          onClick={reset}
          disabled={loading}
          className="text-xs rounded-md bg-red-600 text-white px-3 py-1.5 hover:bg-red-700 disabled:opacity-50"
        >
          {loading ? "Clearing…" : "Yes, reset"}
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="text-xs rounded-md border px-3 py-1.5 hover:bg-[var(--muted)]"
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      className="text-xs text-[var(--muted-foreground)] hover:text-red-500 transition-colors"
    >
      Reset brain
    </button>
  );
}
