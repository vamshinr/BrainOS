"use client";

import { useEffect, useState } from "react";

export type Model = {
  id: string;
  endpoint: string;
  is_text_default: boolean;
  is_vlm_default: boolean;
};

type Defaults = { text: string; vlm: string };

type ModelsResponse = {
  models: Model[];
  defaults: Defaults;
};

let _cache: ModelsResponse | null = null;
let _inflight: Promise<ModelsResponse> | null = null;

async function fetchModels(): Promise<ModelsResponse> {
  if (_cache) return _cache;
  if (_inflight) return _inflight;
  _inflight = fetch("/api/models", { cache: "no-store" })
    .then((r) => r.json())
    .then((j: ModelsResponse) => {
      _cache = j;
      return j;
    })
    .finally(() => {
      _inflight = null;
    });
  return _inflight;
}

/**
 * Dropdown that lets the user override which model handles a request.
 *
 * - `mode="text"` shows the text default first.
 * - `mode="vlm"` shows the VLM default first.
 *
 * Pass the parent's `value` (model id, or empty string for "auto") and `onChange`.
 */
export function ModelPicker({
  value,
  onChange,
  mode = "text",
  label = "Model",
  hint,
}: {
  value: string;
  onChange: (modelId: string) => void;
  mode?: "text" | "vlm";
  label?: string;
  hint?: string;
}) {
  const [models, setModels] = useState<Model[]>([]);
  const [defaults, setDefaults] = useState<Defaults>({ text: "", vlm: "" });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchModels()
      .then((j) => {
        setModels(j.models ?? []);
        setDefaults(j.defaults ?? { text: "", vlm: "" });
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const defaultLabel =
    mode === "vlm" && defaults.vlm
      ? `Auto (${defaults.vlm})`
      : mode === "text" && defaults.text
        ? `Auto (${defaults.text})`
        : "Auto (route default)";

  return (
    <label className="block">
      <div className="flex items-center justify-between mb-1.5">
        <div className="text-[11px] uppercase tracking-widest text-[var(--muted-foreground)]">
          {label}
        </div>
        {hint && (
          <div className="text-[10px] text-[var(--muted-foreground)]">{hint}</div>
        )}
      </div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={loading || models.length === 0}
        className="w-full rounded-md border bg-[var(--card)] px-3 py-2 text-sm font-mono"
      >
        <option value="">{defaultLabel}</option>
        {models.filter((m) => (
          mode === "vlm"
            ? m.is_vlm_default || !m.is_text_default
            : m.is_text_default || !m.is_vlm_default
        )).map((m) => {
          const isDefault =
            (mode === "vlm" && m.is_vlm_default) ||
            (mode === "text" && m.is_text_default);
          return (
            <option key={m.id} value={m.id}>
              {m.id}
              {isDefault ? "  · default" : ""}
            </option>
          );
        })}
      </select>
      {!loading && models.length === 0 && (
        <div className="mt-1 text-[10px] text-amber-600 dark:text-amber-400">
          No models reachable — backend may be down.
        </div>
      )}
    </label>
  );
}
