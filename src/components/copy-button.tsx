"use client";

import { useState } from "react";

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="text-sm rounded-md bg-[var(--foreground)] text-[var(--background)] px-3 py-2 hover:opacity-90"
    >
      {copied ? "Copied" : "Copy SKILLS.md"}
    </button>
  );
}
