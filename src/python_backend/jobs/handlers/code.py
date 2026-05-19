"""Job handler for codebase ingest: file classification, outlines, call graphs, import graphs."""
from __future__ import annotations
import os
import re
import io
import json
import uuid
import time
import zipfile
import tempfile
import subprocess
import shutil
from typing import Optional
from storage.brain import _read_brain, _write_brain
from core.logging import _debug_event, _utc_now_iso
from core.indexes import _build_indexes
from agents import ingest_agent, struct_agent
from clients.router import _resolve_text_override

# ══════════════════════════════════════════════════════════════════════════════
# Code ingest pipeline
# ══════════════════════════════════════════════════════════════════════════════
# Ingests a zip of code OR a single code/doc file. We do NOT embed code bodies
# (that's Cursor's job and a token-cost trap). What we DO extract:
#   • A lightweight file-tree map (path, language, size, category)
#   • Atomic facts from rationale-bearing files (READMEs, ADRs, RFCs,
#     CONTRIBUTING, design docs) via the existing ingest_agent
#   • Ownership facts from CODEOWNERS
#   • Entity ↔ path links so existing entities pick up file references
#
# Output: same shape as other ingest paths (sources/units/entities/relationships
# go into brain.json), plus a codebase summary block on the source record.

_CODE_EXTS = {
    ".py": "python", ".pyi": "python", ".ts": "typescript", ".tsx": "tsx",
    ".js": "javascript", ".jsx": "jsx", ".mjs": "javascript", ".cjs": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift", ".rb": "ruby", ".php": "php", ".cs": "csharp",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".c": "c",
    ".h": "c-header", ".hpp": "cpp-header", ".hh": "cpp-header",
    ".scala": "scala", ".clj": "clojure", ".cljs": "clojurescript",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang",
    ".ml": "ocaml", ".mli": "ocaml", ".fs": "fsharp", ".fsx": "fsharp",
    ".lua": "lua", ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".fish": "fish", ".ps1": "powershell",
    ".html": "html", ".htm": "html", ".css": "css", ".scss": "scss",
    ".sass": "sass", ".less": "less", ".vue": "vue", ".svelte": "svelte",
    ".r": "r", ".R": "r", ".dart": "dart", ".zig": "zig", ".nim": "nim",
    ".jl": "julia", ".sol": "solidity", ".proto": "protobuf",
    ".sql": "sql", ".graphql": "graphql", ".gql": "graphql",
}
_RATIONALE_EXTS = {".md", ".mdx", ".rst", ".adoc", ".org"}
# Note: .txt deliberately excluded — too generic, catches false positives like
# requirements.txt / dependencies.txt / output.txt. Markdown + reStructuredText
# + AsciiDoc + Org-mode are the actual rationale-bearing formats.
_CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".ini", ".env", ".cfg", ".conf"}
_IGNORE_DIRS = {
    "node_modules", ".git", ".venv", "venv", "env", "__pycache__",
    "build", "dist", "out", ".next", ".cache", ".turbo", ".parcel-cache",
    "target", "vendor", "third_party", ".idea", ".vscode", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "coverage", "htmlcov", ".tox",
    "site-packages", "deps", "_build", ".gradle",
}
_IGNORE_FILES = {
    ".DS_Store", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "Cargo.lock", "go.sum", "Gemfile.lock",
    "uv.lock", "bun.lockb",
}
# Hard cap on a single ingested codebase. Anything past this is silently
# truncated; we emit a `truncated=True` flag on the source record.
_MAX_CODE_FILES = 5000
_MAX_FILE_BYTES = 512 * 1024          # 512 KB per rationale file (sane upper bound)
_MAX_RATIONALE_FILES_EXTRACTED = 80   # cap LLM extraction calls per zip


def _classify_file(path: str) -> dict:
    """Return {category, language} for a given relative path. Category is one of
    'code' | 'doc' | 'config' | 'test' | 'owners' | 'adr' | 'other'."""
    name = os.path.basename(path)
    lower = name.lower()
    ext = os.path.splitext(name)[1].lower()
    pdir = path.lower().replace("\\", "/")

    if name == "CODEOWNERS" or lower == "codeowners":
        return {"category": "owners", "language": "codeowners"}

    # ADR / RFC / decision-log heuristic
    if any(seg in pdir for seg in ("/adr/", "/adrs/", "/rfc/", "/rfcs/",
                                    "/decisions/", "/decision-log/")):
        if ext in _RATIONALE_EXTS:
            return {"category": "adr", "language": "markdown" if ext in {".md", ".mdx"} else ext.lstrip(".")}

    if ext in _RATIONALE_EXTS:
        # Notable doc files get a stronger category for downstream weighting
        if lower in {"readme.md", "readme.mdx", "readme.rst", "readme",
                     "contributing.md", "architecture.md", "design.md",
                     "rationale.md"}:
            return {"category": "doc", "language": "markdown"}
        return {"category": "doc", "language": "markdown" if ext in {".md", ".mdx"} else ext.lstrip(".")}

    if ext in _CODE_EXTS:
        if "/test/" in pdir or "/tests/" in pdir or "/__tests__/" in pdir or "_test." in lower or ".test." in lower or ".spec." in lower:
            return {"category": "test", "language": _CODE_EXTS[ext]}
        return {"category": "code", "language": _CODE_EXTS[ext]}

    if ext in _CONFIG_EXTS or lower in {"dockerfile", "makefile", ".gitignore",
                                          ".dockerignore", ".editorconfig"}:
        return {"category": "config", "language": ext.lstrip(".") or "config"}

    return {"category": "other", "language": ext.lstrip(".") or "binary"}


def _should_skip_path(rel_path: str) -> bool:
    """True if any path segment matches an ignore-dir or the filename is
    in IGNORE_FILES."""
    parts = rel_path.replace("\\", "/").split("/")
    for p in parts:
        if p in _IGNORE_DIRS:
            return True
    if parts and parts[-1] in _IGNORE_FILES:
        return True
    return False


def _walk_zip(zip_bytes: bytes) -> list[dict]:
    """Walk a zip archive in-memory. Returns a list of {path, size, ...class}.
    Skips IGNORE_DIRS/FILES. Truncates at _MAX_CODE_FILES."""
    out: list[dict] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # Detect a common top-level directory prefix (e.g. "my-repo-main/") and
        # strip it so paths look natural to the user.
        names = [n for n in zf.namelist() if not n.endswith("/")]
        prefix = ""
        if names:
            firsts = {n.split("/", 1)[0] for n in names}
            if len(firsts) == 1:
                only = next(iter(firsts))
                if any(n.startswith(only + "/") for n in names):
                    prefix = only + "/"
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename[len(prefix):] if prefix and info.filename.startswith(prefix) else info.filename
            if not rel or _should_skip_path(rel):
                continue
            cls = _classify_file(rel)
            out.append({
                "path": rel,
                "size": info.file_size,
                "category": cls["category"],
                "language": cls["language"],
            })
            if len(out) >= _MAX_CODE_FILES:
                break
    return out


def _read_zip_member(zip_bytes: bytes, archive_path_candidates: list[str], max_bytes: int = _MAX_FILE_BYTES) -> Optional[str]:
    """Open a zip and return decoded text for the first matching member, or
    None. We pass *candidates* because the zip may carry a top-level prefix."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members = set(zf.namelist())
        for cand in archive_path_candidates:
            if cand in members:
                try:
                    with zf.open(cand) as fh:
                        return fh.read(max_bytes).decode("utf-8", errors="replace")
                except Exception:
                    return None
    return None


def _parse_codeowners(text: str) -> list[dict]:
    """Parse a CODEOWNERS file (https://docs.github.com/en/repositories/managing-your-repositories-settings-and-features/customizing-your-repository/about-code-owners).
    Returns list of {pattern, owners[]}. Comments and blank lines skipped."""
    out: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern, *owners = parts
        owners = [o for o in owners if o.startswith("@") or "@" in o]
        if owners:
            out.append({"pattern": pattern, "owners": owners})
    return out


def _codeowners_to_units(owners_rules: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Turn CODEOWNERS rules into atomic ownership units + entities +
    relationships. Each rule like `services/billing/  @sarah` becomes:
      unit:   kind=ownership, statement="services/billing/ is owned by @sarah"
      entity: name="@sarah", kind=person
      rel:    @sarah --owns--> services/billing/"""
    units, entities, rels = [], [], []
    seen_owners: set[str] = set()
    for rule in owners_rules:
        pattern = rule["pattern"]
        for owner in rule["owners"]:
            if owner not in seen_owners:
                entities.append({"name": owner, "kind": "person", "aliases": []})
                seen_owners.add(owner)
            units.append({
                "statement": f"{pattern} is owned by {owner} (per CODEOWNERS).",
                "subject": pattern,
                "kind": "ownership",
                "confidence": 0.95,
                "entities": [owner, pattern],
            })
            rels.append({
                "from": owner, "relation": "owns", "to": pattern,
                "confidence": 0.95,
            })
    return units, entities, rels


def _build_tree_summary(files: list[dict]) -> dict:
    """Aggregate the flat file list into a usable summary: language counts,
    directory rollup, top files. The full path list is stored separately."""
    by_lang: dict[str, int] = collections.defaultdict(int)
    by_category: dict[str, int] = collections.defaultdict(int)
    top_dirs: dict[str, int] = collections.defaultdict(int)
    for f in files:
        by_lang[f["language"]] += 1
        by_category[f["category"]] += 1
        top = f["path"].split("/", 1)[0]
        top_dirs[top] += 1
    return {
        "totalFiles": len(files),
        "byLanguage": dict(sorted(by_lang.items(), key=lambda kv: -kv[1])),
        "byCategory": dict(by_category),
        "topLevelDirs": dict(sorted(top_dirs.items(), key=lambda kv: -kv[1])),
    }


def _link_entities_to_paths(entities: list[dict], file_paths: list[str]) -> dict[str, list[str]]:
    """Heuristic entity↔path linker. For each entity, find paths whose any
    segment slug-matches the entity name. e.g. entity 'billing-service' or
    'Billing' matches 'services/billing/*'."""
    def slugs(s: str) -> list[str]:
        s = s.lower().replace("_", "-")
        return [t for t in re.split(r"[^a-z0-9]+", s) if len(t) > 2]

    path_segments: list[tuple[str, set[str]]] = []
    for p in file_paths:
        segs = set()
        for seg in p.lower().split("/"):
            base = os.path.splitext(seg)[0]
            for tok in re.split(r"[^a-z0-9]+", base):
                if len(tok) > 2:
                    segs.add(tok)
        path_segments.append((p, segs))

    out: dict[str, list[str]] = {}
    for ent in entities:
        name = ent.get("name", "")
        if not name or name.startswith("@"):  # skip CODEOWNERS-style people
            continue
        ent_toks = set(slugs(name))
        if not ent_toks:
            continue
        matched = [p for p, segs in path_segments if ent_toks & segs]
        if matched:
            out[name] = matched[:25]  # cap per entity
    return out


# ── Per-file outline extraction ──────────────────────────────────────────────
# Parses code files LOCALLY to produce a structural outline: classes, functions,
# methods, imports, exports. NO LLM, NO embeddings, NO code-body retrieval.
# This is the "shape" of the code an agent needs to know where to look without
# loading the bodies. Bodies stay Cursor's territory.

import ast as _py_ast

_MAX_OUTLINE_BYTES = 200_000  # files larger than this are skipped (huge minified, etc.)
_MAX_SYMBOLS_PER_FILE = 500


def _outline_python(text: str) -> dict:
    """Use the stdlib ast module — robust + accurate for Python."""
    try:
        tree = _py_ast.parse(text)
    except SyntaxError:
        return {"imports": [], "exports": [], "symbols": [], "_error": "syntax"}
    imports: list[str] = []
    symbols: list[dict] = []

    for node in tree.body:
        if isinstance(node, _py_ast.Import):
            for n in node.names:
                imports.append(n.name)
        elif isinstance(node, _py_ast.ImportFrom):
            mod = ("." * (node.level or 0)) + (node.module or "")
            for n in node.names:
                imports.append(f"{mod}.{n.name}" if mod else n.name)
        elif isinstance(node, _py_ast.FunctionDef) or isinstance(node, _py_ast.AsyncFunctionDef):
            symbols.append({
                "name": node.name,
                "kind": "function",
                "line": node.lineno,
                "async": isinstance(node, _py_ast.AsyncFunctionDef),
            })
        elif isinstance(node, _py_ast.ClassDef):
            children = []
            for sub in node.body:
                if isinstance(sub, (_py_ast.FunctionDef, _py_ast.AsyncFunctionDef)):
                    children.append({
                        "name": sub.name,
                        "kind": "method",
                        "line": sub.lineno,
                        "async": isinstance(sub, _py_ast.AsyncFunctionDef),
                    })
            symbols.append({
                "name": node.name, "kind": "class", "line": node.lineno,
                "bases": [_py_ast.unparse(b) for b in node.bases] if hasattr(_py_ast, "unparse") else [],
                "children": children,
            })
        elif isinstance(node, _py_ast.Assign):
            # Top-level CONSTANTS (uppercase names) — useful signal
            for tgt in node.targets:
                if isinstance(tgt, _py_ast.Name) and tgt.id.isupper() and len(tgt.id) > 1:
                    symbols.append({"name": tgt.id, "kind": "const", "line": node.lineno})

    return {
        "imports": imports[:60],
        "exports": [],  # Python doesn't have explicit exports; everything top-level is "exported"
        "symbols": symbols[:_MAX_SYMBOLS_PER_FILE],
    }


# Regex-based outliners for non-Python languages. These are pragmatic — they
# catch ~90% of declarations without parsing the full grammar. For tighter
# accuracy we'd swap in tree-sitter later.

_TS_PATTERNS = {
    "import":     re.compile(r"""^\s*import\s+(?:[^\"']+from\s+)?["']([^"']+)["']""", re.M),
    "import_alt": re.compile(r"""^\s*const\s+\{?[^=]+\}?\s*=\s*require\(["']([^"']+)["']\)""", re.M),
    "export_default": re.compile(r"^\s*export\s+default\s+(?:function|class|const|async\s+function)\s*(\w+)", re.M),
    "export_named":   re.compile(r"^\s*export\s+(?:async\s+)?(?:function|class|const|let|var|type|interface|enum)\s+(\w+)", re.M),
    "function":   re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*[<(]", re.M),
    "arrow_func": re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*(?::\s*[^=]+)?=\s*(?:async\s*)?\(", re.M),
    "class":      re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)", re.M),
    "interface":  re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)", re.M),
    "type_alias": re.compile(r"^\s*(?:export\s+)?type\s+(\w+)\s*=", re.M),
    "enum":       re.compile(r"^\s*(?:export\s+)?enum\s+(\w+)", re.M),
}

def _line_of(text: str, span_start: int) -> int:
    return text.count("\n", 0, span_start) + 1


def _outline_ts(text: str) -> dict:
    imports: list[str] = []
    exports: list[str] = []
    symbols: list[dict] = []
    for m in _TS_PATTERNS["import"].finditer(text):
        imports.append(m.group(1))
    for m in _TS_PATTERNS["import_alt"].finditer(text):
        imports.append(m.group(1))
    for m in _TS_PATTERNS["export_default"].finditer(text):
        exports.append(f"{m.group(1)} (default)")
    for m in _TS_PATTERNS["export_named"].finditer(text):
        exports.append(m.group(1))

    def add(kind: str, pattern: re.Pattern):
        for m in pattern.finditer(text):
            symbols.append({"name": m.group(1), "kind": kind, "line": _line_of(text, m.start())})

    add("function", _TS_PATTERNS["function"])
    add("function", _TS_PATTERNS["arrow_func"])
    add("class",     _TS_PATTERNS["class"])
    add("interface", _TS_PATTERNS["interface"])
    add("type",      _TS_PATTERNS["type_alias"])
    add("enum",      _TS_PATTERNS["enum"])
    # De-dup by (name, kind) — function regex + arrow_func can overlap
    seen = set()
    unique: list[dict] = []
    for s in sorted(symbols, key=lambda s: s["line"]):
        key = (s["name"], s["kind"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(s)
    return {
        "imports": imports[:60],
        "exports": exports[:40],
        "symbols": unique[:_MAX_SYMBOLS_PER_FILE],
    }


_GO_RE_IMPORT = re.compile(r'^\s*"([^"]+)"', re.M)
_GO_RE_IMPORT_BLOCK = re.compile(r"^\s*import\s*\((.*?)\)", re.M | re.S)
_GO_RE_IMPORT_LINE = re.compile(r'^\s*import\s+"([^"]+)"', re.M)
_GO_RE_FUNC = re.compile(r"^\s*func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(", re.M)
_GO_RE_TYPE = re.compile(r"^\s*type\s+(\w+)\s+(?:struct|interface|=)", re.M)

def _outline_go(text: str) -> dict:
    imports: list[str] = []
    for m in _GO_RE_IMPORT_LINE.finditer(text):
        imports.append(m.group(1))
    for blk in _GO_RE_IMPORT_BLOCK.finditer(text):
        for sub in _GO_RE_IMPORT.finditer(blk.group(1)):
            imports.append(sub.group(1))
    symbols = []
    for m in _GO_RE_FUNC.finditer(text):
        symbols.append({"name": m.group(1), "kind": "function", "line": _line_of(text, m.start())})
    for m in _GO_RE_TYPE.finditer(text):
        symbols.append({"name": m.group(1), "kind": "type", "line": _line_of(text, m.start())})
    symbols.sort(key=lambda s: s["line"])
    return {"imports": imports[:60], "exports": [], "symbols": symbols[:_MAX_SYMBOLS_PER_FILE]}


_RUST_RE_USE = re.compile(r"^\s*use\s+([^;]+);", re.M)
_RUST_RE_FN = re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)\s*[<(]", re.M)
_RUST_RE_STRUCT = re.compile(r"^\s*(?:pub\s+)?struct\s+(\w+)", re.M)
_RUST_RE_ENUM = re.compile(r"^\s*(?:pub\s+)?enum\s+(\w+)", re.M)
_RUST_RE_TRAIT = re.compile(r"^\s*(?:pub\s+)?trait\s+(\w+)", re.M)
_RUST_RE_IMPL = re.compile(r"^\s*impl(?:<[^>]+>)?\s+(?:[^{]+for\s+)?(\w+)", re.M)

def _outline_rust(text: str) -> dict:
    imports = [m.group(1).strip() for m in _RUST_RE_USE.finditer(text)]
    symbols = []
    for kind, pat in [("function", _RUST_RE_FN), ("struct", _RUST_RE_STRUCT),
                       ("enum", _RUST_RE_ENUM), ("trait", _RUST_RE_TRAIT),
                       ("impl", _RUST_RE_IMPL)]:
        for m in pat.finditer(text):
            symbols.append({"name": m.group(1), "kind": kind, "line": _line_of(text, m.start())})
    symbols.sort(key=lambda s: s["line"])
    return {"imports": imports[:60], "exports": [], "symbols": symbols[:_MAX_SYMBOLS_PER_FILE]}


_JAVA_RE_IMPORT = re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)\s*;", re.M)
_JAVA_RE_CLASS = re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|abstract\s+|final\s+)*class\s+(\w+)", re.M)
_JAVA_RE_INTERFACE = re.compile(r"^\s*(?:public\s+|private\s+|protected\s+)*interface\s+(\w+)", re.M)
_JAVA_RE_METHOD = re.compile(r"^\s+(?:public|private|protected|static|final|synchronized|abstract|\s)+[\w<>\[\],?\s]+\s+(\w+)\s*\([^)]*\)\s*(?:throws[^{]+)?\{", re.M)

def _outline_java(text: str) -> dict:
    imports = [m.group(1) for m in _JAVA_RE_IMPORT.finditer(text)]
    symbols = []
    for m in _JAVA_RE_CLASS.finditer(text):
        symbols.append({"name": m.group(1), "kind": "class", "line": _line_of(text, m.start())})
    for m in _JAVA_RE_INTERFACE.finditer(text):
        symbols.append({"name": m.group(1), "kind": "interface", "line": _line_of(text, m.start())})
    for m in _JAVA_RE_METHOD.finditer(text):
        nm = m.group(1)
        if nm in {"if", "for", "while", "switch", "return", "catch"}:
            continue
        symbols.append({"name": nm, "kind": "method", "line": _line_of(text, m.start())})
    symbols.sort(key=lambda s: s["line"])
    return {"imports": imports[:60], "exports": [], "symbols": symbols[:_MAX_SYMBOLS_PER_FILE]}


def _extract_outline(path: str, content: str, language: str) -> Optional[dict]:
    """Dispatch outline extraction by language. Returns None if unsupported or
    parsing fails entirely. Per-language failures (bad syntax in one file)
    return a partial result rather than crashing the whole ingest."""
    if len(content.encode("utf-8", errors="ignore")) > _MAX_OUTLINE_BYTES:
        return {"_skipped": "too_large"}
    try:
        if language == "python":
            return _outline_python(content)
        if language in ("typescript", "tsx", "javascript", "jsx"):
            return _outline_ts(content)
        if language == "go":
            return _outline_go(content)
        if language == "rust":
            return _outline_rust(content)
        if language in ("java", "kotlin"):
            return _outline_java(content)
    except Exception as e:
        return {"_error": str(e)[:200], "imports": [], "exports": [], "symbols": []}
    return None  # unsupported language


# ── Call extraction (no LLM) ─────────────────────────────────────────────────
# Pulls callee names + line numbers from a file. We later resolve callees
# against the codebase symbol index. Anything unresolved is dropped — we only
# keep edges that land inside the same codebase, which is what an agent cares
# about ("who in THIS repo calls foo()").

_MAX_CALLS_PER_FILE = 200

def _calls_python(text: str) -> list[dict]:
    """ast-based call extraction. Captures the enclosing function name so
    edges become caller→callee at function granularity."""
    try:
        tree = _py_ast.parse(text)
    except SyntaxError:
        return []
    out: list[dict] = []

    def callee_name(node) -> Optional[str]:
        if isinstance(node, _py_ast.Name):
            return node.id
        if isinstance(node, _py_ast.Attribute):
            # foo.bar.baz() — we record "baz", the rightmost name
            return node.attr
        return None

    class Visitor(_py_ast.NodeVisitor):
        def __init__(self):
            self.stack: list[str] = []

        def visit_FunctionDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node):
            name = callee_name(node.func)
            if name and len(out) < _MAX_CALLS_PER_FILE:
                out.append({
                    "caller": ".".join(self.stack) or "<module>",
                    "callee": name,
                    "line": getattr(node, "lineno", 0),
                })
            self.generic_visit(node)

    Visitor().visit(tree)
    return out


# Regex callees: pragmatic, language-agnostic. Matches `name(` after a word
# boundary; filters out keywords. False positives on `if (x)`, `while (x)` are
# eliminated by the keyword filter.
_CALL_KEYWORDS = {
    "if", "for", "while", "switch", "return", "catch", "throw", "new",
    "await", "async", "yield", "match", "let", "var", "const", "type",
    "import", "export", "function", "class", "interface", "struct", "enum",
    "trait", "impl", "fn", "func", "def", "self", "this", "super",
    "true", "false", "null", "nil", "None", "True", "False",
    "use", "package", "namespace", "module", "in", "of", "is", "as",
    "and", "or", "not", "do", "else", "try", "finally", "with", "from",
}
_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]+)\s*\(")


def _calls_regex(text: str) -> list[dict]:
    """Cheap callee extraction for non-Python languages. Caller resolution is
    intentionally weak — we tag every call to '<file>' so the call graph
    answers 'who calls X' (good) but not 'X calls who from inside Y' (lossy
    without proper scope tracking). Tree-sitter would do this properly."""
    out: list[dict] = []
    for m in _CALL_RE.finditer(text):
        name = m.group(1)
        if name in _CALL_KEYWORDS:
            continue
        out.append({
            "caller": "<file>",
            "callee": name,
            "line": text.count("\n", 0, m.start()) + 1,
        })
        if len(out) >= _MAX_CALLS_PER_FILE:
            break
    return out


def _extract_calls(content: str, language: str) -> list[dict]:
    """Dispatch by language. Returns []  for unsupported langs."""
    if len(content) > _MAX_OUTLINE_BYTES:
        return []
    try:
        if language == "python":
            return _calls_python(content)
        if language in ("typescript", "tsx", "javascript", "jsx",
                          "go", "rust", "java", "kotlin"):
            return _calls_regex(content)
    except Exception:
        return []
    return []


# ── Symbol index ─────────────────────────────────────────────────────────────
# Inverts the per-file outlines into {symbol_name: [{path, kind, line}, ...]}
# so "where is BillingService defined?" is one dict lookup.

_MAX_SYMBOL_OCCURRENCES = 8  # cap per symbol name — overflow truncated

def _build_symbol_index(files: list[dict]) -> dict[str, list[dict]]:
    idx: dict[str, list[dict]] = {}
    for f in files:
        ol = f.get("outline") or {}
        for s in ol.get("symbols") or []:
            name = s.get("name")
            if not name:
                continue
            occ = idx.setdefault(name, [])
            if len(occ) >= _MAX_SYMBOL_OCCURRENCES:
                continue
            occ.append({"path": f["path"], "kind": s.get("kind", "symbol"),
                          "line": s.get("line", 0)})
            # Also index nested methods (one level)
            for child in (s.get("children") or [])[:8]:
                cname = child.get("name")
                if not cname:
                    continue
                cocc = idx.setdefault(cname, [])
                if len(cocc) >= _MAX_SYMBOL_OCCURRENCES:
                    continue
                cocc.append({"path": f["path"], "kind": child.get("kind", "method"),
                                "line": child.get("line", 0), "parent": name})
    return idx


# ── Import / dependency graph ────────────────────────────────────────────────
# Resolves each file's import strings against the file list to produce
# file → file edges. Anything unresolved is bucketed as "external" so we still
# capture third-party dependency counts.

_MAX_IMPORT_EDGES = 30_000

def _resolve_import_python(spec: str, source_path: str, by_module: dict[str, str]) -> Optional[str]:
    """Resolve a python import like 'pkg.sub.mod' or '..mod.thing' against the
    file list. `by_module` maps dotted module path → file path."""
    if not spec:
        return None
    s = spec.strip()
    if s.startswith("."):
        # relative — anchor at source_path's directory
        base = os.path.dirname(source_path)
        dots = 0
        while dots < len(s) and s[dots] == ".":
            dots += 1
        # First dot = current dir; each extra dot pops one up
        for _ in range(dots - 1):
            base = os.path.dirname(base)
        rest = s[dots:]
        rest_dotted = rest.replace(".", "/")
        target = (base + "/" + rest_dotted).lstrip("/") if rest_dotted else base
        for cand in (target + ".py", target + "/__init__.py", target):
            if cand in by_module.values():
                return cand
        return None
    # absolute
    parts = s.split(".")
    # Try longest prefix first: pkg.sub.mod → pkg/sub/mod.py, pkg/sub.py, etc.
    for n in range(len(parts), 0, -1):
        cand = "/".join(parts[:n])
        if cand + ".py" in by_module.values():
            return cand + ".py"
        if cand + "/__init__.py" in by_module.values():
            return cand + "/__init__.py"
    return None


def _resolve_import_relative_path(spec: str, source_path: str, all_paths: set[str]) -> Optional[str]:
    """Resolve a TS/JS-style relative import like './foo' or '../bar/baz'."""
    if not spec.startswith("."):
        return None
    base = os.path.dirname(source_path)
    target = os.path.normpath(os.path.join(base, spec))
    target = target.replace("\\", "/")
    if target.startswith("./"):
        target = target[2:]
    # Try common extensions / index files
    for ext in ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
                  "/index.ts", "/index.tsx", "/index.js", "/index.jsx"):
        cand = target + ext
        if cand in all_paths:
            return cand
    return None


def _build_import_graph(files: list[dict]) -> dict:
    """Return {edges: [{from, to, kind}], external: {spec: count}, stats}."""
    all_paths = {f["path"] for f in files}
    # Build a module → path lookup for python resolution
    by_module: dict[str, str] = {}
    for f in files:
        if f.get("language") == "python":
            p = f["path"]
            mod = p[:-3] if p.endswith(".py") else p
            by_module[mod.replace("/", ".")] = p

    edges: list[dict] = []
    external: dict[str, int] = collections.defaultdict(int)
    seen_edges: set[tuple[str, str]] = set()

    for f in files:
        ol = f.get("outline") or {}
        imports = ol.get("imports") or []
        lang = f.get("language", "")
        src = f["path"]
        for imp in imports:
            target: Optional[str] = None
            if lang == "python":
                target = _resolve_import_python(imp, src, by_module)
            elif lang in ("typescript", "tsx", "javascript", "jsx"):
                target = _resolve_import_relative_path(imp, src, all_paths)
            elif lang == "go":
                # Go imports are usually module paths; only resolve internal ones
                # by matching package directory suffix.
                cand_dir = imp.split("/")[-1] if imp else ""
                if cand_dir:
                    for p in all_paths:
                        if cand_dir in p.split("/") and p.endswith(".go"):
                            target = p
                            break

            if target and target != src:
                key = (src, target)
                if key not in seen_edges and len(edges) < _MAX_IMPORT_EDGES:
                    seen_edges.add(key)
                    edges.append({"from": src, "to": target, "kind": "import"})
            elif not target and imp:
                external[imp] += 1

    # Top external deps (capped)
    top_external = dict(sorted(external.items(), key=lambda kv: -kv[1])[:50])

    # Fan-in / fan-out
    fan_in: dict[str, int] = collections.defaultdict(int)
    fan_out: dict[str, int] = collections.defaultdict(int)
    for e in edges:
        fan_in[e["to"]] += 1
        fan_out[e["from"]] += 1
    hubs = sorted(fan_in.items(), key=lambda kv: -kv[1])[:15]

    return {
        "edges": edges,
        "external": top_external,
        "stats": {
            "internalEdges": len(edges),
            "externalDeps": len(external),
            "hubs": [{"path": p, "fanIn": n} for p, n in hubs],
        },
    }


def _resolve_call_edges(
    raw_calls_by_path: dict[str, list[dict]],
    symbol_index: dict[str, list[dict]],
) -> list[dict]:
    """Turn per-file callee names into resolved edges. Only edges where the
    callee maps to a known symbol in the codebase are kept (anything else is
    a stdlib/external call — noise for an agent)."""
    edges: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for src_path, calls in raw_calls_by_path.items():
        for c in calls:
            callee = c.get("callee")
            occurrences = symbol_index.get(callee or "")
            if not occurrences:
                continue
            # Prefer the unique occurrence; if ambiguous, mark as ambiguous with
            # all candidates as comma-joined. We keep one edge per (src, callee).
            paths = [o["path"] for o in occurrences if o["path"] != src_path]
            if not paths:
                continue
            confidence = 0.9 if len(paths) == 1 else 0.5
            target = paths[0]
            key = (src_path, callee, target)
            if key in seen:
                continue
            seen.add(key)
            edges.append({
                "from": src_path,
                "fromFunc": c.get("caller") or "",
                "to": target,
                "callee": callee,
                "line": c.get("line", 0),
                "confidence": confidence,
                "ambiguous": len(paths) > 1,
            })
            if len(edges) >= _MAX_IMPORT_EDGES:
                return edges
    return edges


# ── Module summaries (auto-wiki) ─────────────────────────────────────────────
# One LLM call per top-level directory. Compresses (README + outline summary +
# top symbols) into a single "what this module is" paragraph. Caps prevent
# token blow-up on large repos.

_MAX_MODULE_SUMMARIES = 12
_MODULE_SUMMARY_INPUT_CHARS = 4500


def _build_module_summary_prompt(dir_name: str, files_in_dir: list[dict],
                                    readme_text: Optional[str]) -> str:
    by_lang = collections.Counter(f["language"] for f in files_in_dir)
    top_syms: list[str] = []
    for f in files_in_dir:
        for s in (f.get("outline") or {}).get("symbols") or []:
            top_syms.append(f"{s.get('kind', '?')} {s.get('name', '?')} ({f['path']})")
            if len(top_syms) >= 25:
                break
        if len(top_syms) >= 25:
            break

    parts = [
        f"Directory: {dir_name}/",
        f"Files: {len(files_in_dir)} · languages: {', '.join(f'{k}:{v}' for k, v in by_lang.most_common(5))}",
        f"Notable symbols: {'; '.join(top_syms) if top_syms else '(none extracted)'}",
    ]
    if readme_text:
        parts.append(f"README excerpt:\n{readme_text[:1800]}")
    body = "\n\n".join(parts)
    return body[:_MODULE_SUMMARY_INPUT_CHARS]


def _generate_module_summaries(
    files: list[dict],
    top_level_dirs: dict[str, int],
    file_text_for_path: dict[str, str],
    model_override: Optional[str],
) -> list[dict]:
    """For each top-level dir (capped at _MAX_MODULE_SUMMARIES, by file count),
    produce a 2-3 sentence "what this module does" via the LLM. Failures are
    swallowed per-dir so one bad call doesn't break the ingest."""
    ranked_dirs = sorted(top_level_dirs.items(), key=lambda kv: -kv[1])[:_MAX_MODULE_SUMMARIES]
    out: list[dict] = []
    for dir_name, _count in ranked_dirs:
        files_in_dir = [f for f in files if f["path"].split("/", 1)[0] == dir_name]
        if len(files_in_dir) < 2:  # skip noise (e.g. a single top-level file)
            continue
        # Find a README-ish doc in this dir
        readme_text: Optional[str] = None
        for f in files_in_dir:
            base = os.path.basename(f["path"]).lower()
            if base.startswith("readme") or base in ("contributing.md", "architecture.md"):
                readme_text = file_text_for_path.get(f["path"])
                if readme_text:
                    break

        prompt_body = _build_module_summary_prompt(dir_name, files_in_dir, readme_text)
        try:
            client, model = _resolve_override("extract", model_override)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content":
                        "You write terse, factual descriptions of code modules. "
                        "Two to three sentences. No marketing language. No invented "
                        "function names — only refer to symbols listed in the input."},
                    {"role": "user", "content":
                        f"Summarize this module:\n\n{prompt_body}\n\n"
                        "Output only the summary text."},
                ],
                max_tokens=180,
                temperature=0.1,
            )
            summary = (resp.choices[0].message.content or "").strip()
            if summary:
                out.append({
                    "dir": dir_name,
                    "fileCount": len(files_in_dir),
                    "languages": dict(collections.Counter(f["language"] for f in files_in_dir).most_common(5)),
                    "summary": summary[:800],
                })
        except Exception as e:
            _debug_event("code.module_summary.error", f"Failed for {dir_name}", error=str(e))
            continue
    return out


# ── Code context for /ask ────────────────────────────────────────────────────
# Surfaces code-map signals when the question matches entity↔path links,
# symbols, or module names. Returns a small list of context lines that get
# inlined into the LLM prompt alongside Facts / Graph / Raw excerpts.

def _code_context_for_query(query: str, brain: dict, limit: int = 6) -> list[str]:
    q = (query or "").lower()
    if not q:
        return []
    code_sources = [s for s in brain.get("sources", [])
                     if s.get("kind") == "code" and s.get("codebase")]
    if not code_sources:
        return []

    lines: list[str] = []
    seen: set[str] = set()

    def push(line: str):
        if line and line not in seen and len(lines) < limit:
            seen.add(line)
            lines.append(line)

    q_tokens = {t for t in re.split(r"[^a-z0-9]+", q) if len(t) > 2}

    for src in code_sources:
        cb = src["codebase"]

        # Entity ↔ path matches
        for ent, paths in (cb.get("entityPaths") or {}).items():
            if ent.lower() in q or any(t in q for t in re.split(r"[^a-z0-9]+", ent.lower()) if len(t) > 2):
                shown = ", ".join(paths[:4])
                more = f" (+{len(paths) - 4} more)" if len(paths) > 4 else ""
                push(f"[code] entity '{ent}' is referenced at: {shown}{more}")

        # Symbol index matches
        sidx = cb.get("symbolIndex") or {}
        for name, occurrences in sidx.items():
            if name.lower() in q_tokens or any(name.lower() in t for t in q_tokens):
                first = occurrences[0]
                more = f" (+{len(occurrences) - 1} more)" if len(occurrences) > 1 else ""
                push(f"[code] symbol '{name}' ({first.get('kind', '?')}) defined at {first['path']}:{first.get('line', 0)}{more}")

        # Module summaries — match dir name in query
        for mod in cb.get("moduleSummaries") or []:
            if mod["dir"].lower() in q_tokens:
                push(f"[code] module '{mod['dir']}/' — {mod['summary']}")

    return lines


def _handler_ingest_code(job: Job, q: JobQueue) -> dict:
    """Worker handler for code/zip ingest. Builds a file-tree map, extracts
    rationale from doc-shaped files, parses CODEOWNERS, links entities to
    paths, and stores everything via struct_agent."""
    p = job.payload
    raw_bytes: bytes = p["data"]
    filename: str = p["filename"]
    is_zip = filename.lower().endswith(".zip")
    title = p["title"]

    q.update_progress(job.id, step="walking archive" if is_zip else "classifying file", progress=0.05)

    if is_zip:
        files = _walk_zip(raw_bytes)
    else:
        # Single-file path. Classify it; treat its content as inline rationale
        # if it's a doc-shaped file, else just record metadata.
        files = [{
            "path": filename,
            "size": len(raw_bytes),
            **_classify_file(filename),
        }]

    if not files:
        raise RuntimeError("Archive contained no ingestable files.")

    summary = _build_tree_summary(files)
    file_paths = [f["path"] for f in files]
    truncated = len(files) >= _MAX_CODE_FILES

    # 1. Parse CODEOWNERS if present.
    owners_units, owners_entities, owners_rels = [], [], []
    if is_zip:
        owners_text = _read_zip_member(raw_bytes, [
            "CODEOWNERS",
            "docs/CODEOWNERS", ".github/CODEOWNERS", ".gitlab/CODEOWNERS",
            # also try with the top-prefix-stripped form by re-prefixing
        ])
        if not owners_text:
            # Try with potential top-level prefix
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                for member in zf.namelist():
                    if os.path.basename(member) == "CODEOWNERS":
                        try:
                            owners_text = zf.open(member).read(_MAX_FILE_BYTES).decode("utf-8", errors="replace")
                            break
                        except Exception:
                            pass
        if owners_text:
            rules = _parse_codeowners(owners_text)
            owners_units, owners_entities, owners_rels = _codeowners_to_units(rules)
    q.update_progress(job.id, step=f"parsed CODEOWNERS ({len(owners_units)} rules)", progress=0.2)

    # 2. Extract atomic facts from rationale-bearing files (capped).
    all_units = list(owners_units)
    all_entities = list(owners_entities)
    all_relationships = list(owners_rels)
    raw_chunks: list[str] = []
    rationale_files = [f for f in files if f["category"] in ("doc", "adr")]
    # Cap extraction work — prefer ADRs over generic docs when over the limit.
    rationale_files.sort(key=lambda f: (0 if f["category"] == "adr" else 1, f["path"]))
    rationale_files = rationale_files[:_MAX_RATIONALE_FILES_EXTRACTED]
    extracted_count = 0

    for idx, f in enumerate(rationale_files, start=1):
        q.update_progress(
            job.id,
            step=f"extracting rationale: {f['path']} ({idx}/{len(rationale_files)})",
            progress=0.2 + 0.55 * (idx / max(len(rationale_files), 1)),
        )
        if is_zip:
            text = _read_zip_member(raw_bytes, [f["path"]])
            if not text:
                # Try with top prefix re-added
                with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                    for member in zf.namelist():
                        if member.endswith(f["path"]) and not member.endswith("/"):
                            try:
                                text = zf.open(member).read(_MAX_FILE_BYTES).decode("utf-8", errors="replace")
                                break
                            except Exception:
                                pass
        else:
            text = raw_bytes.decode("utf-8", errors="replace")
        if not text or not text.strip():
            continue

        source_type = "code/adr" if f["category"] == "adr" else "code/doc"
        ex = ingest_agent.extract_from_text(
            source_type=source_type,
            title=f["path"],
            content=text[:_MAX_EXTRACTION_CHARS],
            model_override=p.get("model"),
        )
        new_units = ex.get("units", []) or []
        # Tag every unit with the originating file path in its evidence so
        # downstream consumers (skill diff, agent context) can pinpoint where
        # a decision came from.
        for u in new_units:
            evid = u.get("evidence") or []
            evid.append({"path": f["path"]})
            u["evidence"] = evid
        all_units.extend(new_units)
        all_entities.extend(ex.get("entities", []) or [])
        all_relationships.extend(ex.get("relationships", []) or [])
        raw_chunks.append(text[:_MAX_EXTRACTION_CHARS])
        if new_units or ex.get("entities") or ex.get("relationships"):
            extracted_count += 1

    # 2b. Per-file structural outline. Parses code locally (no LLM) for
    # classes, functions, methods, imports. Adds an `outline` field to each
    # code-category FileEntry. Bodies are NOT stored — only the symbol shape.
    q.update_progress(job.id, step="parsing file outlines", progress=0.74)

    outline_supported = {"python", "typescript", "tsx", "javascript", "jsx",
                         "go", "rust", "java", "kotlin"}
    outline_targets = [
        f for f in files
        if f["category"] in ("code", "test") and f["language"] in outline_supported
    ]
    outlines_built = 0
    # Collected during the outline pass and consumed afterward:
    raw_calls_by_path: dict[str, list[dict]] = {}
    # Cache file text for README-shaped files so module-summary generation
    # doesn't have to re-open the zip.
    readme_text_by_path: dict[str, str] = {}

    def _maybe_collect_for_summaries(f: dict, text: str):
        base = os.path.basename(f["path"]).lower()
        if base.startswith("readme") or base in {"contributing.md", "architecture.md", "design.md", "rationale.md"}:
            readme_text_by_path[f["path"]] = text[:_MAX_FILE_BYTES]

    if is_zip:
        # One pass through the zip — open every needed file at most once.
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            members_by_basename: dict[str, list[str]] = {}
            for member in zf.namelist():
                if not member.endswith("/"):
                    members_by_basename.setdefault(os.path.basename(member), []).append(member)
            # Build a path → archive-member map so we don't re-scan the zip
            path_to_member: dict[str, str] = {}
            for f in outline_targets:
                cands = members_by_basename.get(os.path.basename(f["path"]), [])
                # Prefer the candidate whose suffix matches the relative path
                best = next((m for m in cands if m.endswith(f["path"])), None)
                if best is None and cands:
                    best = cands[0]
                if best is not None:
                    path_to_member[f["path"]] = best

            for idx, f in enumerate(outline_targets):
                member = path_to_member.get(f["path"])
                if not member:
                    continue
                try:
                    text = zf.open(member).read(_MAX_OUTLINE_BYTES + 1).decode("utf-8", errors="replace")
                except Exception:
                    continue
                outline = _extract_outline(f["path"], text, f["language"])
                if outline is not None:
                    f["outline"] = outline
                    outlines_built += 1
                # Call extraction shares the same file read — cheap to piggyback.
                calls = _extract_calls(text, f["language"])
                if calls:
                    raw_calls_by_path[f["path"]] = calls
                if idx % 20 == 0:
                    q.update_progress(
                        job.id,
                        step=f"parsing outlines ({idx + 1}/{len(outline_targets)})",
                        progress=0.74 + 0.04 * (idx / max(len(outline_targets), 1)),
                    )

            # Pull README-shaped files for module summaries (separate small pass).
            for f in files:
                base = os.path.basename(f["path"]).lower()
                if base.startswith("readme") or base in {"contributing.md", "architecture.md", "design.md", "rationale.md"}:
                    member = path_to_member.get(f["path"])
                    if not member:
                        # Re-resolve via basename map
                        cands = members_by_basename.get(os.path.basename(f["path"]), [])
                        member = next((m for m in cands if m.endswith(f["path"])), cands[0] if cands else None)
                    if member:
                        try:
                            readme_text_by_path[f["path"]] = zf.open(member).read(_MAX_FILE_BYTES).decode("utf-8", errors="replace")
                        except Exception:
                            pass
    else:
        # Single-file ingest path
        f = files[0]
        if f["category"] in ("code", "test") and f["language"] in outline_supported:
            try:
                text = raw_bytes.decode("utf-8", errors="replace")
                outline = _extract_outline(f["path"], text, f["language"])
                if outline is not None:
                    f["outline"] = outline
                    outlines_built += 1
                calls = _extract_calls(text, f["language"])
                if calls:
                    raw_calls_by_path[f["path"]] = calls
            except Exception:
                pass

    q.update_progress(job.id, step="building symbol index", progress=0.78)

    # 3. Entity ↔ path heuristic links.
    entity_paths = _link_entities_to_paths(all_entities, file_paths)

    # 3b. Symbol index, import graph, resolved call graph.
    symbol_index = _build_symbol_index(files)
    import_graph = _build_import_graph(files)
    q.update_progress(job.id, step="resolving call edges", progress=0.82)
    call_edges = _resolve_call_edges(raw_calls_by_path, symbol_index)

    # 3c. Module summaries (auto-wiki). Skipped on tiny ingests where there's
    # only one top-level dir and a handful of files — the LLM call doesn't pay
    # for itself there.
    module_summaries: list[dict] = []
    if len(files) >= 20 and len(summary["topLevelDirs"]) >= 2:
        q.update_progress(job.id, step="summarizing modules (LLM)", progress=0.85)
        module_summaries = _generate_module_summaries(
            files=files,
            top_level_dirs=summary["topLevelDirs"],
            file_text_for_path=readme_text_by_path,
            model_override=p.get("model"),
        )

    # 4. Build the source record. We store the file list + summary as a
    # codebase block on the source — that's the searchable code map.
    source_id = str(uuid.uuid4())[:8]
    now = _utc_now_iso()
    source = {
        "id": source_id,
        "kind": "code",
        "title": title,
        "content": f"Codebase: {title} · {summary['totalFiles']} files · "
                   f"languages: {', '.join(list(summary['byLanguage'].keys())[:5])}",
        "url": p.get("url"),
        "capturedAt": now,
        "codebase": {
            **summary,
            "truncated": truncated,
            "rationaleFilesExtracted": extracted_count,
            "outlinesBuilt": outlines_built,
            "files": files,            # full list — outlines embedded per file
            "entityPaths": entity_paths,
            "symbolIndex": symbol_index,
            "importGraph": import_graph,
            "callEdges": call_edges,
            "moduleSummaries": module_summaries,
        },
    }

    q.update_progress(job.id, step="reconciling + storing", progress=0.88)

    result = struct_agent.embed_and_store(
        source_id=source_id, source=source,
        units=all_units, entities=all_entities,
        relationships=all_relationships,
        raw_chunks=raw_chunks,
    )

    return {
        "source_id": source_id,
        "total_files": summary["totalFiles"],
        "truncated": truncated,
        "languages": summary["byLanguage"],
        "rationale_files_extracted": extracted_count,
        "outlines_built": outlines_built,
        "codeowners_rules": len(owners_units),
        "entity_paths_linked": len(entity_paths),
        "symbols_indexed": len(symbol_index),
        "import_edges": import_graph["stats"]["internalEdges"],
        "external_deps": import_graph["stats"]["externalDeps"],
        "call_edges": len(call_edges),
        "module_summaries": len(module_summaries),
        "units_extracted": len(all_units),
        "entities_extracted": len(all_entities),
        "relationships_extracted": len(all_relationships),
        **result,
    }


