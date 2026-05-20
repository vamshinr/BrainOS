"""Entity canonicalization: dedup, singularize, alias resolution."""
from __future__ import annotations
import re

_ENTITY_TOKEN_RE = re.compile(
    r"(?:\b[a-z][a-z0-9]+(?:-[a-z0-9]+)+\b|/[a-z0-9][a-z0-9_./:-]*|\b[A-Z][A-Za-z0-9]*(?:[A-Z][A-Za-z0-9]*)+\b|\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){0,2}\b)"
)

# ── Entity canonicalization ──────────────────────────────────────────────────
# Collapse variants like "Intel" / "Intel Corp" / "Intel Corporation" / "Intel,
# Inc." onto a single node. We strip corporate suffix tokens and punctuation,
# then compare on a normalized key. Aliases are also indexed so the model can
# emit `{name: "Intel Corporation", aliases: ["Intel"]}` and we'll merge.

_CORP_SUFFIX_TOKENS = {
    "inc", "incorporated", "corp", "corporation", "corporate",
    "ltd", "limited", "llc", "llp", "lp", "co", "company",
    "gmbh", "ag", "sa", "sas", "plc", "kg", "nv", "bv", "oy",
    "aps", "srl", "sl", "sarl", "kk", "pty",
    "holdings", "group", "holding", "industries",
}

_ARTICLE_TOKENS = {"the", "a", "an"}

_ENT_PUNCT_RE = re.compile(r"[.,;:'’\"!?()\[\]/&]+")


def _singularize(token: str) -> str:
    """Crude English plural → singular. Conservative on short tokens to avoid
    mangling proper nouns ('AMD' stays 'AMD'). Handles the common cases:
      companies → company   tomatoes → tomato   apples → apple
      boxes → box           processes → process  buses (kept as bus only via 's' rule below)
    Skips known non-plural endings: 'ss', 'is', 'us', 'os', 'as'.
    """
    if len(token) <= 3:
        return token
    # 'ies' → 'y'   (companies, policies, batteries)
    if token.endswith("ies") and token[-4] not in "aeiou":
        return token[:-3] + "y"
    # 'oes' → 'o'   (tomatoes, potatoes, heroes)
    if token.endswith("oes") and len(token) > 4:
        return token[:-2]
    # '(s|x|z|sh|ch)es' → drop 'es'  (boxes, dishes, brushes, processes)
    if (token.endswith(("ses", "xes", "zes", "shes", "ches"))) and len(token) > 4:
        return token[:-2]
    # plain trailing 's', but skip false plurals
    if (token.endswith("s")
            and not token.endswith(("ss", "is", "us", "os", "as"))):
        return token[:-1]
    return token


def _canonical_entity_key(name: str) -> str:
    """Normalized comparison key. Steps applied in order:
      1. lowercase + strip punctuation
      2. drop leading articles  ("the AMD" / "an Onion" → "AMD" / "Onion")
      3. drop trailing corporate suffixes  ("Intel Corp" / "Intel, Inc." → "Intel")
      4. singularize each remaining token  ("tomatoes" → "tomato", "companies" → "company")
    So 'intel', 'Intel Corp', 'Intel, Inc.', 'The Intel Corporation' all
    canonicalize to 'intel'. Tomato / Tomatoes / tomato. AMD / The AMD. Etc.
    """
    if not name:
        return ""
    s = _ENT_PUNCT_RE.sub(" ", name.lower())
    s = re.sub(r"\s+", " ", s).strip()
    parts = s.split(" ")
    while len(parts) > 1 and parts[0] in _ARTICLE_TOKENS:
        parts.pop(0)
    while len(parts) > 1 and parts[-1] in _CORP_SUFFIX_TOKENS:
        parts.pop()
    parts = [_singularize(p) for p in parts]
    return " ".join(parts).strip()


def _entity_canonical_keys(entity: dict) -> set[str]:
    """All canonical keys identifying this entity (name + every alias)."""
    keys: set[str] = {_canonical_entity_key(entity.get("name", ""))}
    for a in entity.get("aliases", []) or []:
        keys.add(_canonical_entity_key(a))
    keys.discard("")
    return keys


def _pick_canonical_name(candidates: list[str]) -> str:
    """Pick the most canonical-looking display name from a list of variants.
    Heuristics:
      1. Prefer names that *have* a corporate suffix (more disambiguated).
      2. Then prefer the longest.
      3. Stable tiebreaker: first occurrence.
    """
    if not candidates:
        return ""
    def has_suffix(n: str) -> bool:
        last = n.lower().strip(".,").split()[-1] if n.strip() else ""
        return last in _CORP_SUFFIX_TOKENS
    ranked = sorted(
        enumerate(candidates),
        key=lambda iv: (not has_suffix(iv[1]), -len(iv[1]), iv[0]),
    )
    return ranked[0][1]


def _consolidate_entities(brain: dict) -> dict[str, str]:
    """Group `brain['entities']` by canonical key and merge duplicates in place.

    Returns a rename map {old_display_name: canonical_display_name} that the
    caller should apply to relationships and units so all references converge.
    Idempotent: a brain already free of duplicates returns {}.
    """
    entities = brain.get("entities", []) or []
    by_key: dict[str, list[dict]] = {}
    for ent in entities:
        for k in _entity_canonical_keys(ent):
            by_key.setdefault(k, []).append(ent)

    # Union-find: walk the key→entities map and group entities that share any key.
    seen_ids: set[int] = set()
    groups: list[list[dict]] = []
    for group_seed in by_key.values():
        unseen = [e for e in group_seed if id(e) not in seen_ids]
        if not unseen:
            continue
        group: list[dict] = []
        stack = list(unseen)
        while stack:
            ent = stack.pop()
            if id(ent) in seen_ids:
                continue
            seen_ids.add(id(ent))
            group.append(ent)
            for k in _entity_canonical_keys(ent):
                for sib in by_key.get(k, []):
                    if id(sib) not in seen_ids:
                        stack.append(sib)
        if group:
            groups.append(group)

    rename_map: dict[str, str] = {}
    survivors: list[dict] = []
    for group in groups:
        if len(group) == 1:
            survivors.append(group[0])
            continue
        # Merge group into one canonical entity
        names = [g["name"] for g in group if g.get("name")]
        canonical_name = _pick_canonical_name(names)
        winner = next(g for g in group if g["name"] == canonical_name)
        aliases: set[str] = set()
        for g in group:
            for a in g.get("aliases", []) or []:
                if a and a != canonical_name:
                    aliases.add(a)
            if g["name"] != canonical_name:
                aliases.add(g["name"])
                rename_map[g["name"]] = canonical_name
        winner["aliases"] = sorted(aliases)
        survivors.append(winner)

    # Preserve original ordering when nothing was merged, otherwise rebuild.
    if rename_map:
        # Keep relative order of first-occurrence of each surviving id
        order = {id(e): i for i, e in enumerate(entities)}
        survivors.sort(key=lambda e: order.get(id(e), 1 << 30))
        brain["entities"] = survivors
    return rename_map


def _apply_entity_renames(brain: dict, rename_map: dict[str, str]) -> None:
    """Rewrite stale entity names across relationships and units in place."""
    if not rename_map:
        return
    for rel in brain.get("relationships", []) or []:
        if rel.get("from") in rename_map:
            rel["from"] = rename_map[rel["from"]]
        if rel.get("to") in rename_map:
            rel["to"] = rename_map[rel["to"]]
    for u in brain.get("units", []) or []:
        if u.get("subject") in rename_map:
            u["subject"] = rename_map[u["subject"]]
        ents = u.get("entities") or []
        if ents:
            u["entities"] = sorted({rename_map.get(e, e) for e in ents if e})


def _build_entity_resolver(entities: list[dict]):
    """Return a callable that maps any name variant to the canonical display
    name. A 'variant' is any string whose canonical key matches the canonical
    key of an existing entity's name or aliases. Returns the input unchanged
    when no match is found, so unknown names pass through.

    Used at insert-time so freshly-extracted relationships and unit subjects/
    entities never reference a name that isn't in brain['entities']."""
    exact: dict[str, str] = {}       # lowercased name/alias → canonical display
    by_key: dict[str, str] = {}      # canonical key → canonical display
    for ent in entities or []:
        display = (ent.get("name") or "").strip()
        if not display:
            continue
        exact[display.lower()] = display
        key = _canonical_entity_key(display)
        if key:
            by_key.setdefault(key, display)
        for a in ent.get("aliases") or []:
            if not a:
                continue
            exact[a.lower()] = display
            ak = _canonical_entity_key(a)
            if ak:
                by_key.setdefault(ak, display)

    def resolve(name: str) -> str:
        if not name:
            return name
        hit = exact.get(name.lower())
        if hit:
            return hit
        key = _canonical_entity_key(name)
        if key and key in by_key:
            return by_key[key]
        return name

    return resolve


def _fallback_entities_from_text(text: str) -> list[str]:
    """Best-effort retrieval aliases from raw text; these are not asserted facts."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _ENTITY_TOKEN_RE.findall(text or ""):
        value = match.strip(".,;:()[]{}'\"")
        if len(value) < 3:
            continue
        if value.lower() in {
            "the", "and", "or", "but", "for", "with", "from", "this", "that",
            "when", "then", "before", "after", "source", "title",
        }:
            continue
        key = value.lower()
        if key not in seen:
            seen.add(key)
            found.append(value)
    return found[:80]


