"use client";

import { useMemo, useState } from "react";

export interface FileOutlineSymbol {
  name: string;
  kind: string;
  line: number;
  async?: boolean;
  bases?: string[];
  children?: FileOutlineSymbol[];
}

export interface FileOutline {
  imports: string[];
  exports: string[];
  symbols: FileOutlineSymbol[];
  _skipped?: string;
  _error?: string;
}

export interface FileEntry {
  path: string;
  size: number;
  category: string;
  language: string;
  outline?: FileOutline;
}

interface TreeNode {
  name: string;
  fullPath: string;     // empty for root
  children: Map<string, TreeNode>;
  file?: FileEntry;     // present on leaf nodes
  fileCount: number;    // recursive count for folders
  totalBytes: number;   // recursive sum
  byCategory: Map<string, number>;
}

function buildTree(files: FileEntry[]): TreeNode {
  const root: TreeNode = {
    name: "",
    fullPath: "",
    children: new Map(),
    fileCount: 0,
    totalBytes: 0,
    byCategory: new Map(),
  };
  for (const f of files) {
    const parts = f.path.split("/").filter(Boolean);
    let cur = root;
    for (let i = 0; i < parts.length; i++) {
      const name = parts[i];
      const isLeaf = i === parts.length - 1;
      cur.fileCount += 1;
      cur.totalBytes += f.size;
      cur.byCategory.set(f.category, (cur.byCategory.get(f.category) ?? 0) + 1);

      let child = cur.children.get(name);
      if (!child) {
        child = {
          name,
          fullPath: parts.slice(0, i + 1).join("/"),
          children: new Map(),
          fileCount: 0,
          totalBytes: 0,
          byCategory: new Map(),
        };
        cur.children.set(name, child);
      }
      if (isLeaf) {
        child.file = f;
        child.fileCount = 1;
        child.totalBytes = f.size;
        child.byCategory.set(f.category, 1);
      }
      cur = child;
    }
  }
  return root;
}

const CAT_TINT: Record<string, string> = {
  code:    "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  doc:     "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  adr:     "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  test:    "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  config:  "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  owners:  "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300",
  other:   "bg-zinc-100 text-zinc-600 dark:bg-zinc-800/50 dark:text-zinc-400",
};

function dominantCategory(node: TreeNode): string {
  let best = "other";
  let bestN = 0;
  for (const [k, v] of node.byCategory.entries()) {
    if (v > bestN) { best = k; bestN = v; }
  }
  return best;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}

function Row({
  node,
  depth,
  defaultOpen,
}: {
  node: TreeNode;
  depth: number;
  defaultOpen: boolean;
}) {
  const isFolder = !node.file;
  // Folders open by default at top depth; leaves always start collapsed
  // (otherwise outline panels would pop open en masse).
  const [open, setOpen] = useState(isFolder ? defaultOpen : false);

  if (isFolder) {
    const cat = dominantCategory(node);
    const childList = Array.from(node.children.values()).sort((a, b) => {
      // folders before files, then alpha
      const aFolder = !a.file ? 0 : 1;
      const bFolder = !b.file ? 0 : 1;
      if (aFolder !== bFolder) return aFolder - bFolder;
      return a.name.localeCompare(b.name);
    });
    return (
      <>
        <div
          className="flex items-center gap-2 px-3 py-1 hover:bg-[var(--muted)]/40 cursor-pointer text-sm select-none"
          style={{ paddingLeft: `${depth * 16 + 12}px` }}
          onClick={() => setOpen((o) => !o)}
        >
          <span className="inline-block w-3 text-[var(--muted-foreground)] text-[10px]">
            {open ? "▾" : "▸"}
          </span>
          <span className={`size-1.5 rounded-full ${CAT_TINT[cat]?.split(" ")[0] ?? "bg-zinc-300"}`} />
          <span className="font-medium font-mono truncate">{node.name || "/"}</span>
          <span className="ml-auto flex items-center gap-2 text-[10px] text-[var(--muted-foreground)] font-mono tabular-nums">
            <span>{node.fileCount} {node.fileCount === 1 ? "file" : "files"}</span>
            <span>{formatBytes(node.totalBytes)}</span>
          </span>
        </div>
        {open && childList.map((child) => (
          <Row
            key={child.fullPath || child.name}
            node={child}
            depth={depth + 1}
            defaultOpen={depth < 1}
          />
        ))}
      </>
    );
  }

  // Leaf file — has an inline expandable outline when one was extracted.
  const f = node.file!;
  const hasOutline = !!(f.outline && (
    f.outline.symbols.length > 0 ||
    f.outline.imports.length > 0 ||
    f.outline.exports.length > 0
  ));
  return (
    <>
      <div
        className={`flex items-center gap-2 px-3 py-1 hover:bg-[var(--muted)]/40 text-xs ${hasOutline ? "cursor-pointer" : ""}`}
        style={{ paddingLeft: `${depth * 16 + 28}px` }}
        onClick={() => hasOutline && setOpen((o) => !o)}
      >
        {hasOutline ? (
          <span className="inline-block w-3 text-[var(--muted-foreground)] text-[10px]">
            {open ? "▾" : "▸"}
          </span>
        ) : (
          <span className="inline-block w-3" />
        )}
        <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-medium ${CAT_TINT[f.category] ?? CAT_TINT.other}`}>
          {f.category}
        </span>
        <span className="font-mono truncate flex-1">{node.name}</span>
        {hasOutline && f.outline && (
          <span className="text-[10px] text-[var(--accent)] font-mono tabular-nums">
            {f.outline.symbols.length} sym
          </span>
        )}
        <span className="text-[10px] text-[var(--muted-foreground)] font-mono">{f.language}</span>
        <span className="text-[10px] text-[var(--muted-foreground)] font-mono tabular-nums ml-2">
          {formatBytes(f.size)}
        </span>
      </div>
      {open && f.outline && <OutlinePanel outline={f.outline} depth={depth + 1} />}
    </>
  );
}

const SYMBOL_TINT: Record<string, string> = {
  class:     "text-purple-600 dark:text-purple-400",
  interface: "text-blue-600 dark:text-blue-400",
  type:      "text-blue-600 dark:text-blue-400",
  enum:      "text-amber-600 dark:text-amber-400",
  struct:    "text-emerald-600 dark:text-emerald-400",
  trait:     "text-rose-600 dark:text-rose-400",
  impl:      "text-rose-600 dark:text-rose-400",
  function:  "text-zinc-700 dark:text-zinc-300",
  method:    "text-zinc-700 dark:text-zinc-300",
  const:     "text-amber-600 dark:text-amber-400",
};

function OutlinePanel({ outline, depth }: { outline: FileOutline; depth: number }) {
  const padLeft = `${depth * 16 + 28}px`;
  return (
    <div
      className="border-l-2 border-[var(--accent)]/30 ml-3 my-1 bg-[var(--muted)]/15"
      style={{ marginLeft: padLeft }}
    >
      {/* Imports */}
      {outline.imports.length > 0 && (
        <div className="px-3 py-1.5">
          <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">
            imports ({outline.imports.length})
          </div>
          <div className="flex flex-wrap gap-1">
            {outline.imports.slice(0, 12).map((imp, i) => (
              <span
                key={i}
                className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-[var(--muted)]/60 text-[var(--muted-foreground)]"
              >
                {imp}
              </span>
            ))}
            {outline.imports.length > 12 && (
              <span className="text-[10px] text-[var(--muted-foreground)]">
                +{outline.imports.length - 12}
              </span>
            )}
          </div>
        </div>
      )}

      {/* Exports (TS/JS only — Python returns []) */}
      {outline.exports.length > 0 && (
        <div className="px-3 py-1.5 border-t border-[var(--muted)]/40">
          <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">
            exports
          </div>
          <div className="flex flex-wrap gap-1">
            {outline.exports.map((e, i) => (
              <span
                key={i}
                className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
              >
                {e}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Symbols */}
      {outline.symbols.length > 0 && (
        <div className="px-3 py-1.5 border-t border-[var(--muted)]/40">
          <div className="text-[10px] uppercase tracking-widest text-[var(--muted-foreground)] mb-1">
            symbols ({outline.symbols.length})
          </div>
          <ul className="font-mono text-[11px] space-y-0.5">
            {outline.symbols.slice(0, 80).map((s, i) => (
              <SymbolRow key={i} symbol={s} />
            ))}
            {outline.symbols.length > 80 && (
              <li className="text-[10px] text-[var(--muted-foreground)] pl-3">
                … +{outline.symbols.length - 80} more
              </li>
            )}
          </ul>
        </div>
      )}

      {outline._skipped && (
        <div className="px-3 py-2 text-[10px] text-[var(--muted-foreground)]">
          outline skipped: {outline._skipped}
        </div>
      )}
      {outline._error && (
        <div className="px-3 py-2 text-[10px] text-red-600 dark:text-red-400">
          parse error: {outline._error}
        </div>
      )}
    </div>
  );
}

function SymbolRow({ symbol }: { symbol: FileOutlineSymbol }) {
  const color = SYMBOL_TINT[symbol.kind] ?? "text-[var(--foreground)]";
  return (
    <li>
      <div className="flex items-baseline gap-2">
        <span className="text-[9px] uppercase tracking-wide text-[var(--muted-foreground)] w-12 shrink-0">
          {symbol.kind}
        </span>
        <span className={`${color} font-medium`}>
          {symbol.async ? "async " : ""}
          {symbol.name}
        </span>
        {symbol.bases && symbol.bases.length > 0 && (
          <span className="text-[10px] text-[var(--muted-foreground)]">
            extends {symbol.bases.join(", ")}
          </span>
        )}
        <span className="text-[10px] text-[var(--muted-foreground)] ml-auto tabular-nums">
          L{symbol.line}
        </span>
      </div>
      {symbol.children && symbol.children.length > 0 && (
        <ul className="ml-14 mt-0.5 space-y-0.5">
          {symbol.children.slice(0, 30).map((child, i) => (
            <li
              key={i}
              className="flex items-baseline gap-2 text-[10px] text-[var(--muted-foreground)]"
            >
              <span className="opacity-60">↳</span>
              <span>{child.async ? "async " : ""}{child.name}()</span>
              <span className="ml-auto tabular-nums">L{child.line}</span>
            </li>
          ))}
          {symbol.children.length > 30 && (
            <li className="text-[10px] text-[var(--muted-foreground)] pl-3">
              … +{symbol.children.length - 30} more
            </li>
          )}
        </ul>
      )}
    </li>
  );
}

export function FileTree({ files }: { files: FileEntry[] }) {
  const tree = useMemo(() => buildTree(files), [files]);
  const topLevel = Array.from(tree.children.values()).sort((a, b) => {
    const aFolder = !a.file ? 0 : 1;
    const bFolder = !b.file ? 0 : 1;
    if (aFolder !== bFolder) return aFolder - bFolder;
    return a.name.localeCompare(b.name);
  });

  if (files.length === 0) {
    return (
      <div className="rounded-lg border bg-[var(--card)] px-4 py-6 text-center text-xs text-[var(--muted-foreground)]">
        No files captured.
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-[var(--card)] overflow-hidden">
      <div className="flex items-center gap-3 px-3 py-2 border-b bg-[var(--muted)]/30 text-[10px] uppercase tracking-widest text-[var(--muted-foreground)]">
        <span className="flex-1">tree</span>
        <span>{tree.fileCount} {tree.fileCount === 1 ? "file" : "files"} · {formatBytes(tree.totalBytes)}</span>
      </div>
      <div className="max-h-[60vh] overflow-y-auto py-1">
        {topLevel.map((node) => (
          <Row
            key={node.fullPath || node.name}
            node={node}
            depth={0}
            defaultOpen={true}
          />
        ))}
      </div>
    </div>
  );
}
