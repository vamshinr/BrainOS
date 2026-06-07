# Cross-Chunk Entity Resolution — Implementation Plan

> Closes the largest remaining gap in graph quality: short names, aliases, and pronouns that appear across different chunks become separate nodes instead of merging into one canonical entity.

**Date:** 2026-05-30
**Status:** proposed
**Companion:** the existing chunker framework + the "Sophisticated Entity Resolution" roadmap item

---

## Table of contents

- [Cross-Chunk Entity Resolution — Implementation Plan](#cross-chunk-entity-resolution--implementation-plan)
  - [Table of contents](#table-of-contents)
  - [1. The gap, with three concrete failure modes](#1-the-gap-with-three-concrete-failure-modes)
  - [2. What we have today and why it breaks](#2-what-we-have-today-and-why-it-breaks)
  - [3. The layered solution](#3-the-layered-solution)
  - [4. Worked example — 5 chunks, 4 people, 1 collision](#4-worked-example--5-chunks-4-people-1-collision)
    - [The document](#the-document)
    - [Which failure mode each line hits](#which-failure-mode-each-line-hits)
    - [What the alias table looks like at the end of each chunk](#what-the-alias-table-looks-like-at-the-end-of-each-chunk)
    - [Expected final graph (success criteria)](#expected-final-graph-success-criteria)
  - [5. L1 — Sliding context window](#5-l1--sliding-context-window)
  - [6. L2 — Per-document alias table](#6-l2--per-document-alias-table)
    - [6.1 Data structures](#61-data-structures)
    - [6.2 Alias generation rules (deterministic, no LLM)](#62-alias-generation-rules-deterministic-no-llm)
    - [6.3 What the prompt prefix looks like (chunk N+1)](#63-what-the-prompt-prefix-looks-like-chunk-n1)
    - [6.4 Gender / number tracking](#64-gender--number-tracking)
    - [6.5 Ambiguity flag in the graph](#65-ambiguity-flag-in-the-graph)
    - [6.6 Memory bounds](#66-memory-bounds)
  - [7. L3 — Post-hoc embedding fuzzy merge](#7-l3--post-hoc-embedding-fuzzy-merge)
  - [8. L4 — Coreference pre-pass (optional)](#8-l4--coreference-pre-pass-optional)
  - [9. Implementation map — where each change lives](#9-implementation-map--where-each-change-lives)
  - [10. Test plan](#10-test-plan)
    - [10.1 Unit tests](#101-unit-tests)
    - [10.2 Integration test — the canonical 5-chunk document](#102-integration-test--the-canonical-5-chunk-document)
    - [10.3 Regression tests](#103-regression-tests)
    - [10.4 Metric to watch in prod](#104-metric-to-watch-in-prod)
  - [11. Rollout phases](#11-rollout-phases)
  - [12. Risks and gotchas](#12-risks-and-gotchas)
  - [13. Open decisions](#13-open-decisions)
  - [14. TL;DR](#14-tldr)

---

## 1. The gap, with three concrete failure modes

| # | Failure mode | Example | Today's outcome |
|---|---|---|---|
| F1 | **Same-chunk pronoun** | One chunk says "Lal Mohandas opened a PR. He noted Sarah reviewed it." | Usually resolved correctly by the LLM in one call. ~5% miss rate. |
| F2 | **Cross-chunk short name** | Chunk 1 says "Lal Mohandas". Chunk 3 says "Lal then merged the PR." | Two separate PERSON nodes: `Lal Mohandas` and `Lal`. |
| F3 | **Cross-chunk pronoun** | Chunk 1 says "Lal Mohandas". Chunk 2 says "He pushed a fix." | Either `He` becomes a fake PERSON node, or the action is silently dropped. |
| F4 | **Collision** | Document mentions both "John Smith" and "John Doe". A later chunk just says "John". | Currently merged to whichever was extracted first — or left as new ambiguous node. |
| F5 | **Title / initial variants** | "Dr. Mohandas", "L. Mohandas", "Mohandas" all appear | Three separate nodes. |

Failure modes F2 through F5 are the ones cross-chunk extraction architecturally cannot solve in a single LLM call — each chunk is sent to the model in isolation, so the model has no way to know what was extracted from earlier chunks.

---

## 2. What we have today and why it breaks

```
IngestOrchestrator.ingest(text)
    └─ Chunker.chunk(text) → chunks: list[str]
       └─ for chunk in chunks:
              entities, relations = EntityExtractor.extract(chunk)
              GraphStore.upsert_entities(entities, relations)
```

- `EntityExtractor.extract(chunk)` sees only the current chunk string.
- Each call is stateless. No "document memory" lives between iterations.
- The graph upsert uses `(name, type)` as the natural key, so `Lal` and `Lal Mohandas` end up as two distinct PERSON nodes.

That is the entire architectural cause. Every fix below is about giving the extractor enough surrounding context to resolve short names and pronouns back to their canonical form.

---

## 3. The layered solution

| Layer | What it does | Catches | Cost | Build complexity |
|---|---|---|---|---|
| **L1** | Sliding context window — prepend last N sentences of previous chunk as read-only context | F1, most F3 | Negligible | Low |
| **L2** | Per-document alias table — track every canonical name + its short-form aliases + most-recent-mention pointer; pass as a structured hint to each chunk's extraction prompt | F2, F4, F5, residual F3 | One in-memory dict per document | Medium |
| **L3** | Post-hoc embedding fuzzy merge — after all chunks ingest, embed every entity name, merge pairs above similarity threshold | Whatever L1+L2 missed | One embedding pass per document | Medium |
| **L4** | Coreference pre-pass — run a coref model on the whole document, rewrite pronouns to canonical names before chunking | The hardest residual F3 cases | One coref model call per document | High |

**Recommendation:** L1 + L2 ship together as Phase 1. They solve ~80% of the problem with low risk. L3 ships as Phase 2 once we measure residual error. L4 is optional and only needed for pronoun-dense corpora (literary, legal narrative).

---

## 4. Worked example — 5 chunks, 4 people, 1 collision

This is the canonical test document. Every chunk exercises a different failure mode. Use it to validate the implementation and to write the integration tests.

### The document

```
[CHUNK 1]
Lal Mohandas opened the pull request for the new auth service.
He noted that Sarah Patel had reviewed his earlier work and
suggested several improvements.

[CHUNK 2]
Lal then added John Smith as a reviewer. John had previously
worked on a similar service. Sarah commented that his expertise
would be valuable.

[CHUNK 3]
She approved the PR after John addressed her comments. Mohandas
thanked her and merged the change.

[CHUNK 4]
Later that week, John Doe filed a bug against the new service.
He reported that authentication was failing intermittently.

[CHUNK 5]
Lal investigated and found the root cause. He pushed a fix and
asked John to retest. John confirmed the issue was resolved.
```

### Which failure mode each line hits

| Chunk | Line | Failure mode it triggers |
|---|---|---|
| 1 | "He noted" | F1 — same-chunk pronoun (LLM resolves in one call) |
| 2 | "Lal then added" | F2 — cross-chunk short name (L1 helps, L2 nails it) |
| 2 | "Sarah commented" | F2 — same as above for Sarah |
| 2 | "his expertise" | F1 — same-chunk pronoun |
| 3 | "She approved" | F3 — cross-chunk pronoun (requires L2 pronoun sidecar) |
| 3 | "John addressed" | F2 — short name (still unambiguous at this point) |
| 3 | "Mohandas thanked" | F5 — surname-only reference (L2 alias table) |
| 4 | "John Doe filed" | F4 setup — introduces collision |
| 4 | "He reported" | F3 — pronoun, but should bind to John Doe (most recent male) |
| 5 | "Lal investigated" | F2 + F3 — short name, then pronoun |
| 5 | "asked John to retest" | F4 — AMBIGUOUS, could be Smith or Doe; recency favours Doe |

### What the alias table looks like at the end of each chunk

After chunk 1:
```python
aliases_by_type = {
  "PERSON": {
    "Lal":      [("Lal Mohandas", chunk=1)],
    "Mohandas": [("Lal Mohandas", chunk=1)],
    "Sarah":    [("Sarah Patel",  chunk=1)],
    "Patel":    [("Sarah Patel",  chunk=1)],
  }
}
last_pronoun_referent = {
  "male":    ("Lal Mohandas", chunk=1),
  "female":  ("Sarah Patel",  chunk=1),
  "neutral": None,
}
```

After chunk 2 (adds John Smith):
```python
aliases_by_type = {
  "PERSON": {
    "Lal":      [("Lal Mohandas", chunk=1)],
    "Mohandas": [("Lal Mohandas", chunk=1)],
    "Sarah":    [("Sarah Patel",  chunk=1)],
    "Patel":    [("Sarah Patel",  chunk=1)],
    "John":     [("John Smith",   chunk=2)],
    "Smith":    [("John Smith",   chunk=2)],
  }
}
last_pronoun_referent = {
  "male":   ("John Smith",  chunk=2),   # bumped — most recent male
  "female": ("Sarah Patel", chunk=1),
}
```

After chunk 3 (no new entities, just refs):
```python
# aliases unchanged; only the recency timestamps update
"Lal":      [("Lal Mohandas", chunk=3)],   # bumped by "Mohandas thanked"
"Mohandas": [("Lal Mohandas", chunk=3)],
"Sarah":    [("Sarah Patel",  chunk=3)],   # bumped by "She approved" → Sarah
"Patel":    [("Sarah Patel",  chunk=3)],
"John":     [("John Smith",   chunk=3)],   # bumped by "John addressed"
"Smith":    [("John Smith",   chunk=3)],

last_pronoun_referent = {
  "male":   ("Lal Mohandas", chunk=3),   # last male mentioned was Mohandas
  "female": ("Sarah Patel",  chunk=3),
}
```

After chunk 4 (introduces John Doe — COLLISION):
```python
"John":  [("John Smith", chunk=3), ("John Doe", chunk=4)],   # AMBIGUOUS now
"Doe":   [("John Doe", chunk=4)],
"Smith": [("John Smith", chunk=3)],

last_pronoun_referent = {
  "male":   ("John Doe", chunk=4),    # most recent male
  "female": ("Sarah Patel", chunk=3),
}
```

After chunk 5 — the planner correctly handles ambiguity:
```python
# Chunk 5's prompt receives:
#   AMBIGUOUS "John" → could be John Smith OR John Doe
#   Most recently mentioned male: Lal Mohandas (after chunk 5's "Lal investigated")
#
# The LLM sees "asked John to retest. John confirmed the issue was resolved."
# Context: the issue was reported by John Doe in chunk 4. The LLM should
# choose John Doe based on the surrounding "the issue was resolved" cue.
# If it cannot disambiguate, the entity is tagged confidence: low and goes
# to the curation queue.
```

### Expected final graph (success criteria)

| Canonical PERSON node | Aliases the resolver merged into it | Mentioned in chunks |
|---|---|---|
| Lal Mohandas | Lal, Mohandas, He (chunk 1, 5) | 1, 2, 3, 5 |
| Sarah Patel | Sarah, Patel, She/her (chunk 3) | 1, 2, 3 |
| John Smith | Smith | 2, 3 |
| John Doe | Doe, He (chunk 4) | 4, 5 (low-confidence link from chunk 5) |

**Today's wrong outcome** without this work: 8–11 PERSON nodes instead of 4 (Lal + Lal Mohandas + Mohandas + Sarah + Sarah Patel + Patel + John + John Smith + John Doe + Smith + Doe — depending on which chunks the LLM partially resolved).

---

## 5. L1 — Sliding context window

The cheapest fix. Before extracting from chunk N, prepend the last 2–3 sentences of chunk N-1 to the prompt, but mark them as "context only, do not re-extract":

```
=== CONTEXT FROM PREVIOUS CHUNK (do not extract from this section) ===
Lal Mohandas opened the pull request for the new auth service.
He noted that Sarah Patel had reviewed his earlier work and
suggested several improvements.

=== EXTRACT ENTITIES AND RELATIONS FROM THIS SECTION ONLY ===
Lal then added John Smith as a reviewer. John had previously
worked on a similar service. Sarah commented that his expertise
would be valuable.
```

The LLM now has enough lexical context to resolve "Lal" to "Lal Mohandas" and "Sarah" to "Sarah Patel" inside its own pass.

**Limitation:** breaks down across 3+ chunk gaps. If "Lal" appears in chunk 1 and then again in chunk 7, the sliding window is gone. L2 covers that case.

**Tuning knob:** number of sentences carried over. Default 2. Configurable per ontology via `chunker_configs.context_sentences`.

---

## 6. L2 — Per-document alias table

### 6.1 Data structures

Two in-memory structures, scoped to a single document ingestion:

```python
@dataclass
class AliasRegistry:
    # Bucketed by entity type so "John" the PERSON can't collide
    # with "John" the COMPANY.
    aliases_by_type: dict[str, dict[str, list[AliasCandidate]]]

    # Positional sidecar for pronouns. Updated every chunk based on
    # the most recent mention of a typed-and-gendered entity.
    last_pronoun_referent: dict[str, tuple[str, int] | None]
    # keys: "male", "female", "neutral"


@dataclass
class AliasCandidate:
    canonical_name: str
    last_seen_chunk: int
    mention_count: int = 1
```

A canonical name maps to itself in the alias table (so "Lal Mohandas" → "Lal Mohandas" is also stored). This makes the lookup symmetric.

### 6.2 Alias generation rules (deterministic, no LLM)

For each newly extracted PERSON entity `name`:

1. Strip titles: `Dr|Mr|Mrs|Ms|Prof|Sir|Lord|Madam|Lady` (case-insensitive, with or without trailing dot)
2. Split on whitespace → tokens
3. Emit aliases:
   - Full original (e.g. `"Lal Mohandas"`)
   - First token (`"Lal"`)
   - Last token (`"Mohandas"`)
   - Initial form (`"L. Mohandas"`) — only if first token > 1 char
4. Drop any alias < 3 chars (avoids "A", "I" noise)
5. Drop any alias that is a common stop-word or pronoun

For ORG / PRODUCT / LOCATION entity types, use simpler rules (full name + last significant token only).

### 6.3 What the prompt prefix looks like (chunk N+1)

The orchestrator builds this from the current `AliasRegistry` state and prepends it to the extraction prompt:

```
=== KNOWN ENTITIES IN THIS DOCUMENT SO FAR ===
PERSON:
  - Lal Mohandas      (aliases: "Lal", "Mohandas", "L. Mohandas")
  - Sarah Patel       (aliases: "Sarah", "Patel", "S. Patel")
  - John Smith        (aliases: "Smith", "J. Smith")
  - John Doe          (aliases: "Doe", "J. Doe")

AMBIGUOUS ALIASES (require local-context disambiguation):
  - "John" → could refer to John Smith OR John Doe; use surrounding text

MOST RECENTLY MENTIONED (use for pronoun resolution):
  - he/him/his   → most recent male:    John Doe (chunk 4)
  - she/her/hers → most recent female:  Sarah Patel (chunk 3)
  - it/its       → most recent neutral: (none)

INSTRUCTIONS:
  - When you encounter an alias from the list above, resolve it to its
    canonical name in your extraction output.
  - When the alias is AMBIGUOUS, prefer the candidate that fits the
    local sentence context. If you cannot decide, return the alias
    as-is and set `confidence: 0.5`.
  - Pronouns should resolve to the "most recently mentioned" entity of
    matching gender unless the surrounding text clearly contradicts.
```

### 6.4 Gender / number tracking

Two options for assigning gender to a PERSON entity:

**Option A — Ask the LLM during extraction.** Add a `gender_hint: male|female|neutral|unknown` field to the extraction schema. Cheap (one extra field), reasonably reliable for clearly gendered names.

**Option B — Don't track gender at all; just track "most recent PERSON".** Simpler, but the LLM has to do all the pronoun work from positional cues alone.

**Recommendation:** Option A. Cost is one extra JSON field per entity; reliability uplift on pronoun resolution is significant.

When `gender_hint` is `unknown`, fall back to "most recent PERSON of any gender" for that pronoun bucket.

### 6.5 Ambiguity flag in the graph

When the LLM resolves an alias that was marked AMBIGUOUS in the prompt, the extractor should set:

```python
entity.confidence_score = 0.5      # default for ambiguous-source resolution
entity.metadata["resolved_from_alias"] = "John"
entity.metadata["alias_was_ambiguous"] = True
entity.metadata["alias_candidates"] = ["John Smith", "John Doe"]
```

These records flow to:
- The graph (so we never silently merge low-confidence)
- The curation queue UI for human review

### 6.6 Memory bounds

A typical 50-page SDLC document has ~30 unique PERSON entities. Alias map stays under 200 lines of prompt text, well within any reasonable LLM context.

For 1000-page documents (rare): apply a **recency window** — only include entities mentioned in the last K=10 chunks in the prompt prefix. Older entities still live in the registry; they just don't appear in the prompt until their alias is matched in the current chunk via string search (which triggers their inclusion).

---

## 7. L3 — Post-hoc embedding fuzzy merge

Runs once, at the end of `IngestOrchestrator.ingest()`, after all chunks are processed.

```
for each entity type in {PERSON, ORG, PRODUCT, LOCATION}:
    candidates = graph.list_entities_in_document(doc_id, type)
    embeddings = embedder.embed_batch([e.name for e in candidates])
    for each pair (a, b) where cosine_sim(a, b) >= 0.85:
        if name_compatible(a.name, b.name):
            merge(a, b)  # b's relations re-attach to a
            audit_log_merge(a, b, similarity_score)
```

Catches:
- Spelling variants: "Mohandas" vs "Mohandass"
- Initial forms L2 missed: "L Mohandas" vs "Lal Mohandas"
- Reordered names: "Patel, Sarah" vs "Sarah Patel"

`name_compatible` is a guard against false positives:
- Same entity type
- Token-set overlap ≥ 1 substantive token
- No conflicting honorifics ("Dr. Smith" vs "Mr. Smith" — different people probably)

Merges are reversible from the audit log for 30 days.

---

## 8. L4 — Coreference pre-pass (optional)

Heavy. Only build if metrics from Phases 1+2 show residual pronoun error > 10%.

```
text = parser.parse(file)
coref_map = coref_model.resolve(text)
# coref_map = {(chunk_idx, token_idx): "canonical_name", ...}
rewritten_text = rewrite_pronouns(text, coref_map)
# Now feed rewritten_text into the existing chunker
```

Two delivery options:
- **In-process small model:** `fastcoref` (CPU, ~200MB, ~3s per page)
- **LLM call:** Send whole document to Claude, get a coref map back. Higher cost, higher quality.

Either way: this layer mutates the source text before chunking. The original text is preserved in `cake.documents.raw_text`; the rewritten version is what feeds `Chunker.chunk()`. Both are stored so we can compare downstream.

---

## 9. Implementation map — where each change lives

| Layer | File | Change |
|---|---|---|
| L1 | `app/ingestion/orchestrator.py` | New `_build_context_prefix(prev_chunk, n_sentences)` helper; called before each `EntityExtractor.extract()` call |
| L1 | `app/services/extraction/base.py` | `extract()` signature gains optional `context_prefix: str = ""` arg |
| L1 | `app/services/extraction/openai.py`, `anthropic.py`, `noop.py` | Each concrete extractor concatenates `context_prefix` into its prompt template |
| L2 | `app/ingestion/alias_registry.py` | NEW — `AliasRegistry`, `AliasCandidate`, `generate_aliases()` |
| L2 | `app/ingestion/orchestrator.py` | Instantiate one `AliasRegistry` per `ingest()` call; update after every chunk; pass `registry.render_prompt_block()` into each extraction |
| L2 | `app/services/extraction/base.py` | `extract()` gains `alias_prompt: str = ""` arg |
| L2 | `app/services/extraction/openai.py`, `anthropic.py` | Concatenate `alias_prompt` into prompt template |
| L2 | `app/services/extraction/schemas.py` | Entity schema gains `gender_hint: Literal["male","female","neutral","unknown"]` and `metadata: dict` (already exists) |
| L3 | `app/services/entity_resolution/fuzzy_merge.py` | NEW — embedding-based merge service |
| L3 | `app/ingestion/orchestrator.py` | After all chunks ingest, call `fuzzy_merge.run(doc_id)` |
| L3 | `alembic/versions/0057_*.py` | NEW table `cake.entity_merges` (audit log of every merge, with reversal pointer) |
| L4 | `app/services/coref/` | NEW package — `CorefService` protocol + fastcoref / LLM implementations + factory |
| L4 | `app/ingestion/orchestrator.py` | If `coref_enabled`, run before `Chunker.chunk()` |
| Config | `app/runtime_config/keys.py` | New keys: `entity_resolution.l1_enabled`, `l1_context_sentences`, `l2_enabled`, `l2_recency_window`, `l3_enabled`, `l3_similarity_threshold`, `l4_enabled`, `l4_provider` |
| UI | `app/ui/index.html` | New "Resolution Confidence" column on entities list; "Ambiguous mentions" badge on document detail |

---

## 10. Test plan

### 10.1 Unit tests

`tests/unit/ingestion/test_alias_registry.py`:
- `generate_aliases("Lal Mohandas")` → `{"Lal Mohandas", "Lal", "Mohandas", "L. Mohandas"}`
- `generate_aliases("Dr. Sarah Patel")` → strips title → same shape as Sarah Patel
- `generate_aliases("Ed")` → only emits `"Ed"` once, no spurious aliases
- Adding "John Smith" then "John Doe" → `aliases["John"]` has length 2 (collision recorded)
- Pronoun tracker updated correctly for male/female/neutral
- Recency timestamps bump on re-mention even with no new entity
- `render_prompt_block()` includes ambiguous-alias warnings only when alias has > 1 candidate
- `render_prompt_block()` respects `recency_window` for large alias maps

`tests/unit/ingestion/test_context_prefix.py`:
- Last 2 sentences of a 5-sentence chunk extracted correctly
- Chunk with single sentence → returns the whole thing
- Empty previous chunk → returns empty string

### 10.2 Integration test — the canonical 5-chunk document

`tests/integration/test_cross_chunk_resolution.py`:

```python
def test_canonical_5_chunk_document(client, fake_extractor):
    """Ingest the document from § 4 and assert the final graph state.

    fake_extractor is wired to return deterministic per-chunk extractions
    matching what a real LLM would produce given the prompt prefix —
    this isolates the orchestrator logic from LLM variability.
    """
    doc = open("tests/fixtures/cross_chunk_canonical.txt").read()
    resp = client.post("/ingest-text", json={"text": doc, "doc_type": "narrative"})
    assert resp.status_code == 200

    doc_id = resp.json()["doc_id"]
    entities = client.get(f"/admin/documents/{doc_id}/entities").json()
    persons = [e for e in entities if e["type"] == "PERSON"]

    # Exactly 4 canonical PERSON nodes
    assert len(persons) == 4
    names = {p["name"] for p in persons}
    assert names == {"Lal Mohandas", "Sarah Patel", "John Smith", "John Doe"}

    # John Smith and John Doe both exist (collision preserved, not merged)
    smith = next(p for p in persons if p["name"] == "John Smith")
    doe = next(p for p in persons if p["name"] == "John Doe")

    # The chunk 5 "John" mention should resolve to John Doe with low confidence
    assert any(
        m["chunk_idx"] == 5 and m["confidence_score"] < 0.7
        for m in doe["mentions"]
    )

    # Lal Mohandas should have mentions from chunks 1, 2, 3, 5
    lal = next(p for p in persons if p["name"] == "Lal Mohandas")
    chunk_idxs = {m["chunk_idx"] for m in lal["mentions"]}
    assert chunk_idxs == {1, 2, 3, 5}
```

### 10.3 Regression tests

- Ingest the existing test corpus (no alias work needed) and assert entity count is unchanged ± 5%
- A document with zero PERSONs (pure technical doc) → no overhead, no alias-block prompt bloat
- A document with one entity mentioned 50 times → alias map stays at size 1, prompt block stays small

### 10.4 Metric to watch in prod

Add a new dashboard widget: **Average aliases-merged-per-document** + **Ambiguous-resolution rate**. If ambiguous rate stays high, that's the trigger to invest in L4.

---

## 11. Rollout phases

**Phase 1 — L1 + L2 (target: 1 week of focused work)**
- Behind runtime flag `entity_resolution.l1_enabled` and `l2_enabled`, both default `false`
- Enable on `narrative`, `confluence`, `jira-comment` ontologies first; leave `code` and `legal_clause` alone (they have their own resolution patterns)
- Measure: alias-merge count, ambiguous-resolution rate, total PERSON node count per document
- Compare against a 100-document held-out baseline before / after

**Phase 2 — L3 (target: 3 days after Phase 1 ships)**
- Behind `entity_resolution.l3_enabled`, default `false`
- Run on Phase 1's held-out corpus, measure additional merges caught
- New audit table `cake.entity_merges` with reversal capability
- Curation queue UI lists every merge with a "split back" button (admin only)

**Phase 3 — L4 (optional, build only if needed)**
- Triggered by ambiguous-resolution rate > 10% in production data
- Start with `fastcoref` (in-process, no extra service); only upgrade to LLM coref if results insufficient

---

## 12. Risks and gotchas

| Risk | Mitigation |
|---|---|
| L1's "do not extract from context" instruction is sometimes ignored by smaller LLMs → duplicate entities | Post-extraction dedup: if entity name matches a name in the context prefix and chunk text doesn't actually mention it, drop |
| L2 alias map grows unbounded on huge documents | Recency window (default K=10 chunks); fall back to lookup-by-string-match for older entries |
| Gender hints carry social bias (e.g. "Alex" → male incorrectly) | Treat `unknown` as the default; only set male/female when the LLM is confident |
| L3 fuzzy merge over-merges distinct people with similar names | High threshold (0.85), name_compatible guard, reversible via audit log, human review queue |
| Pronoun tracker bumped incorrectly when a sentence has multiple people | Use the LAST named entity in the sentence; if uncertain, mark `male: None` for next chunk (force the LLM to look at context) |
| Ambiguous resolution silently picks wrong candidate | Surfaces in the graph with `confidence_score=0.5` + `alias_was_ambiguous=true`; goes to the curation queue |
| Per-document alias registry leaks memory across `ingest()` calls | `AliasRegistry` is local to one `ingest()` invocation; goes out of scope when ingest completes |
| Two parallel ingests of different documents share a registry | Don't. Registry is per-`ingest()`-call, not a module-level singleton |
| Re-ingesting the same document creates duplicate merge audit rows | Migration `0057` adds `UNIQUE(canonical_id, merged_id)` so re-runs are no-ops |

---

## 13. Open decisions

1. **Gender hint provenance** — A (LLM-supplied) or B (positional only)? Lean A.
2. **Default L1 context size** — 2 sentences or 1 paragraph? Lean 2 sentences (less noise).
3. **L3 similarity threshold** — 0.85 or 0.88? Lean 0.85, tune after measuring.
4. **L4 coref backend** — fastcoref vs LLM? Defer until Phase 3 trigger fires.
5. **Per-ontology rollout** — opt-in or opt-out? Lean opt-in for Phase 1 (`narrative`, `confluence`, `jira-comment`), opt-out from Phase 2.
6. **Curation queue scope** — only ambiguous resolutions, or also every L3 merge above some threshold? Lean both, with a tab split.

---

## 14. TL;DR

1. The bug is architectural: each chunk is sent to the LLM in isolation, so "Lal" in chunk 3 has no way to know it's the same person as "Lal Mohandas" in chunk 1.
2. Four-layer fix. Layers 1 and 2 ship together as Phase 1 and solve ~80% of the problem cheaply.
3. The 5-chunk canonical example in § 4 exercises every failure mode (same-chunk pronoun, cross-chunk short name, cross-chunk pronoun, name collision, surname-only reference) and becomes the integration test.
4. Per-document alias table is bucketed by entity type, stores candidate lists (so collisions are tracked, not silently overwritten), and carries a positional pronoun sidecar separate from the name map.
5. Ambiguous resolutions land in the graph with `confidence_score=0.5` and are routed to a human curation queue rather than silently merged.

Phase 1 alone is ~1 week of focused work. Say **start Phase 1** and the implementation order is: `alias_registry.py` (new) → orchestrator wiring → extractor prompt updates → unit tests → integration test against the canonical document.