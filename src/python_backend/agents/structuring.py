"""StructuringAgent: embed units, reconcile, merge into brain.json."""
from __future__ import annotations
import uuid
import datetime
import time
from clients.router import _resolve_text_override
from storage.brain import _read_brain, _write_brain
from storage.chroma import collection
from core.logging import _debug_event, _log_call, _utc_now_iso
from core.indexes import _build_indexes
from core.entities import _consolidate_entities, _apply_entity_renames
from core.temporal import _temporal_fields, _infer_temporal_status
from agents.prompts import RECONCILE_SYSTEM
from agents.extraction import _parse_extraction_json

class StructuringAgent:
    """
    Embeds knowledge units into ChromaDB, runs reconciliation against existing units,
    and syncs the merged state to brain.json for the Next.js frontend.
    """

    def _reconcile(self, new_unit: dict, new_uid: str, source_id: str) -> dict:
        """
        Query ChromaDB for semantically similar existing units from other sources.
        If any are found above the similarity threshold, call the 70B model once
        to classify the relationship. Returns superseded IDs and duplicate flag.
        """
        total = collection.count()
        if total < 2:
            return {"superseded_ids": [], "duplicate": False, "conflicts_with": []}

        try:
            # Query without a where filter to avoid ChromaDB errors when no docs
            # match the compound condition. We post-filter by kind and source_id.
            results = collection.query(
                query_texts=[new_unit["statement"]],
                n_results=min(6, total),
            )
        except Exception:
            return {"superseded_ids": [], "duplicate": False, "conflicts_with": []}

        ids = results["ids"][0] if results["ids"] else []
        distances = results["distances"][0] if results["distances"] else []
        docs = results["documents"][0] if results["documents"] else []
        metas = results["metadatas"][0] if results["metadatas"] else []

        # Post-filter: cosine distance < 0.30. Allow cross-kind (e.g. an
        # ownership statement may semantically supersede a fact). Allow
        # same-source (the LLM often emits old + new ownership in one chunk).
        candidates = [
            {
                "id": cid,
                "statement": doc,
                "kind": m.get("kind", ""),
                "subject": m.get("subject", ""),
                "distance": dist,
            }
            for cid, dist, doc, m in zip(ids, distances, docs, metas)
            if dist < 0.30 and cid != new_uid and (m or {}).get("doc_type", "unit") == "unit"
        ]

        if not candidates:
            return {"superseded_ids": [], "duplicate": False, "conflicts_with": []}

        # Single LLM call covering all candidates
        candidates_text = "\n".join(
            f'  [{c["id"]}] (kind={c["kind"]}, similarity {1 - c["distance"]:.2f}) "{c["statement"]}"'
            for c in candidates
        )
        prompt = (
            f"NEW UNIT:\n"
            f'  kind: {new_unit["kind"]}\n'
            f'  subject: {new_unit["subject"]}\n'
            f'  statement: "{new_unit["statement"]}"\n\n'
            f"EXISTING SIMILAR UNITS:\n{candidates_text}\n\n"
            f"Pick the single most relevant existing unit. Apply the decision rules.\n"
            f'Return JSON with target_id set to the id of the matching existing unit.'
        )
        client, model = router.get("reconcile")
        t0 = time.time()
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": RECONCILE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=160,
                temperature=0.0,
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(resp, "usage", None)
            result = _parse_extraction_json(resp.choices[0].message.content)
            verdict = result.get("verdict", "independent")
            target_id = result.get("target_id")
            _log_call(
                "reconcile", model, latency_ms,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                note=f"verdict={verdict}",
            )
            print(f"[Reconcile] verdict={verdict} target={target_id} reason={result.get('reason','')}")

            if verdict == "duplicate":
                return {"superseded_ids": [], "duplicate": True, "conflicts_with": []}
            if verdict == "supersedes" and target_id:
                return {"superseded_ids": [target_id], "duplicate": False, "conflicts_with": []}
            if verdict == "conflicts" and target_id:
                return {"superseded_ids": [], "duplicate": False, "conflicts_with": [target_id]}
        except Exception as e:
            _log_call("reconcile", model, int((time.time() - t0) * 1000), ok=False, note=str(e)[:80])
            print(f"[Reconcile] LLM error: {e}")

        return {"superseded_ids": [], "duplicate": False, "conflicts_with": []}

    def embed_and_store(
        self,
        source_id: str,
        source: dict,
        units: list,
        entities: list,
        relationships: list | None = None,
        raw_chunks: list[str] | None = None,
    ) -> dict:
        now = _utc_now_iso()
        _debug_event(
            "store.start",
            "Preparing extracted data for storage",
            source_id=source_id,
            source_kind=source.get("kind"),
            units_in=len(units),
            entities_in=len(entities),
            relationships_in=len(relationships or []),
            raw_chunks=len(raw_chunks or []),
        )

        # ── Step 1: build unit objects ──────────────────────────────────────
        # The LLM often splits subject ("Alice Chen") and statement ("owns
        # billing service") into separate fields. We normalize every statement
        # to be self-contained BEFORE writing to brain.json or ChromaDB so
        # that SKILLS.md, retrieval, and answers all use the complete sentence.
        def _normalize_statement(u: dict) -> str:
            stmt = u.get("statement", "").strip()
            subj = u.get("subject", "").strip()
            if subj and subj.lower() not in stmt.lower():
                return f"{subj} {stmt}"
            return stmt

        VALID_DEPTS = {"engineering", "product", "legal", "finance", "hr",
                       "sales", "marketing", "operations", "security", "general"}

        pending = []
        for u in units:
            uid = str(uuid.uuid4())[:10]
            dept = (u.get("department") or "general").strip().lower()
            if dept not in VALID_DEPTS:
                dept = "general"
            temporal = _temporal_fields(u, source)
            # Preserve any pre-attached evidence entries (e.g. {"path": "..."}
            # set by the code-ingest handler so the /code page can locate ADR
            # units). Prepend the canonical sourceId/quote entry; filter out
            # any prior evidence that already pointed at this same source to
            # avoid double-counting.
            prior_evidence = [
                e for e in (u.get("evidence") or [])
                if isinstance(e, dict) and e.get("sourceId") != source_id
            ]
            pending.append((uid, {
                "id": uid,
                "kind": u.get("kind", "fact"),
                "department": dept,
                "subject": u.get("subject", ""),
                "statement": _normalize_statement(u),  # always self-contained
                "entities": u.get("entities", []),
                "sector": u.get("sector", "General"),
                "evidence": [{"sourceId": source_id, "quote": u.get("evidence_quote", "")}, *prior_evidence],
                "confidence": float(u.get("confidence", 0.7)),
                "createdAt": now,
                "updatedAt": now,
                **temporal,
            }))

        # ── Step 2: upsert all into ChromaDB first so reconciliation can query ──
        # The document text must be self-contained — prepend subject when the
        # LLM omitted it from the statement (e.g. "owns the billing service"
        # becomes "Alice Chen owns the billing service").
        def _full_text(unit: dict) -> str:
            stmt = unit.get("statement", "")
            subj = unit.get("subject", "")
            if subj and subj.lower() not in stmt.lower():
                return f"{subj} {stmt}"
            return stmt

        if pending:
            _debug_event(
                "store.chroma.upsert",
                "Upserting units into ChromaDB",
                source_id=source_id,
                pending_units=len(pending),
            )
            collection.upsert(
                ids=[uid for uid, _ in pending],
                documents=[_full_text(unit) for _, unit in pending],
                metadatas=[{
                    "doc_type": "unit",
                    "source_id": source_id,
                    "kind": unit["kind"],
                    "subject": unit["subject"],
                    "confidence": unit["confidence"],
                    "entities": ",".join(unit.get("entities", [])),  # ChromaDB requires scalar
                    "sector": unit.get("sector", "General"),
                    "department": unit.get("department", "general"),
                } for _, unit in pending],
            )

        # ── Step 3: reconcile each new unit against existing ones ───────────
        superseded_ids: set[str] = set()
        stored_units = []
        # conflict pairs: target_existing_id -> set of new_unit_ids that conflict with it
        conflict_pairs: dict[str, set[str]] = {}

        for uid, unit in pending:
            rec = self._reconcile(unit, uid, source_id)
            if rec["duplicate"]:
                # Remove the just-upserted duplicate from ChromaDB
                try:
                    collection.delete(ids=[uid])
                except Exception:
                    pass
                continue
            if unit.get("temporalStatus") == "future":
                unit["pendingSupersedes"] = rec["superseded_ids"]
            else:
                superseded_ids.update(rec["superseded_ids"])
            for target_id in rec["conflicts_with"]:
                conflict_pairs.setdefault(target_id, set()).add(uid)
                # Mark the new unit as disputed and store back-reference
                unit["disputed"] = True
                unit.setdefault("conflictsWith", []).append(target_id)
            stored_units.append(unit)

        _debug_event(
            "store.reconcile.done",
            "Reconciliation complete",
            source_id=source_id,
            pending_units=len(pending),
            stored_units=len(stored_units),
            superseded=len(superseded_ids),
            conflict_targets=len(conflict_pairs),
        )

        # ── Step 4: merge into brain.json ───────────────────────────────────
        brain = _read_brain()

        if not isinstance(brain.get("rawChunks"), list):
            brain["rawChunks"] = []
        new_raw_chunks = []
        for idx, chunk in enumerate(raw_chunks or [], start=1):
            text = (chunk or "").strip()
            if not text:
                continue
            chunk_id = f"{source_id}:chunk:{idx}"
            entry = {
                "id": chunk_id,
                "sourceId": source_id,
                "sourceTitle": source.get("title", ""),
                "kind": source.get("kind", "doc"),
                "chunkIndex": idx,
                "text": text[:6000],
                "charCount": len(text),
                "createdAt": now,
            }
            brain["rawChunks"].insert(0, entry)
            new_raw_chunks.append(entry)

        if new_raw_chunks:
            _debug_event(
                "store.chroma.raw_chunks",
                "Upserting raw source chunks into ChromaDB",
                source_id=source_id,
                raw_chunks=len(new_raw_chunks),
            )
            collection.upsert(
                ids=[chunk["id"] for chunk in new_raw_chunks],
                documents=[chunk["text"] for chunk in new_raw_chunks],
                metadatas=[{
                    "doc_type": "raw_chunk",
                    "source_id": source_id,
                    "source_title": chunk.get("sourceTitle", ""),
                    "kind": chunk.get("kind", "doc"),
                    "chunk_index": chunk.get("chunkIndex", 0),
                } for chunk in new_raw_chunks],
            )

        # Entity dedup by canonical key (handles "Intel" / "Intel Corporation" /
        # "Intel Corp" / "Intel, Inc." → one node). Match against existing
        # names AND aliases via _canonical_entity_key; merge aliases on collision.
        new_entities = []
        for e in entities:
            raw_name = (e.get("name") or "").strip()
            if not raw_name:
                continue
            incoming_aliases = [a.strip() for a in (e.get("aliases") or []) if a and a.strip()]
            incoming_keys = {_canonical_entity_key(raw_name)}
            for a in incoming_aliases:
                incoming_keys.add(_canonical_entity_key(a))
            incoming_keys.discard("")

            existing = None
            for x in brain["entities"]:
                if incoming_keys & _entity_canonical_keys(x):
                    existing = x
                    break

            if existing:
                # Merge incoming name + aliases into the existing entity's
                # aliases, keeping the existing display name as canonical.
                aliases = set(existing.get("aliases") or [])
                if raw_name.lower() != (existing.get("name") or "").lower():
                    aliases.add(raw_name)
                for a in incoming_aliases:
                    if a.lower() != (existing.get("name") or "").lower():
                        aliases.add(a)
                existing["aliases"] = sorted(aliases)
            else:
                entity = {
                    "id": str(uuid.uuid4())[:8],
                    "name": raw_name,
                    "kind": e.get("kind", "concept"),
                    "aliases": incoming_aliases,
                }
                brain["entities"].insert(0, entity)
                new_entities.append(entity)

        # Resolve every incoming entity reference (relationship endpoints, unit
        # subjects, unit entity arrays) against the now-canonicalized entity
        # list. Prevents this-ingest's edges/units from pointing at a name
        # that's only an alias of an existing canonical entity — which would
        # otherwise spawn a phantom node on the graph view.
        resolve_entity = _build_entity_resolver(brain["entities"])
        for su in stored_units:
            if su.get("subject"):
                su["subject"] = resolve_entity(su["subject"])
            if su.get("entities"):
                su["entities"] = sorted({resolve_entity(e) for e in su["entities"] if e})

        # Mark superseded units as stale in brain.json
        superseded_count = 0
        for bu in brain["units"]:
            if bu["id"] in superseded_ids and not bu.get("stale"):
                bu["stale"] = True
                bu["supersededBy"] = stored_units[0]["id"] if stored_units else "unknown"
                bu["supersededAt"] = now
                if not bu.get("validTo"):
                    bu["validTo"] = now[:10]
                bu["temporalStatus"] = "historical"
                superseded_count += 1

        # Mark existing units as disputed when a new unit conflicts with them.
        disputed_count = 0
        for bu in brain["units"]:
            if bu["id"] in conflict_pairs:
                bu["disputed"] = True
                existing = set(bu.get("conflictsWith", []))
                existing.update(conflict_pairs[bu["id"]])
                bu["conflictsWith"] = list(existing)
                disputed_count += 1

        brain["units"] = stored_units + brain["units"]
        brain["sources"].insert(0, source)

        # ── Step 5: merge relationships into brain graph ───────────────────
        if not isinstance(brain.get("relationships"), list):
            brain["relationships"] = []

        new_rels = []
        first_unit_id = stored_units[0]["id"] if stored_units else "unknown"
        for r in (relationships or []):
            frm = r.get("from", "").strip()
            to = r.get("to", "").strip()
            rel = r.get("relation", "").strip()
            conf = float(r.get("confidence", 0.7))
            if not (frm and to and rel):
                continue
            # Deduplicate: skip if identical edge already in brain
            duplicate = any(
                x["from"] == frm and x["to"] == to and x["relation"] == rel
                for x in brain["relationships"]
            )
            if duplicate:
                continue
            edge = {
                "id": str(uuid.uuid4())[:8],
                "from": frm,
                "relation": rel,
                "to": to,
                "unitId": first_unit_id,
                "sourceId": source_id,
                "confidence": conf,
                "createdAt": now,
            }
            brain["relationships"].insert(0, edge)
            new_rels.append(edge)

        # ── Step 6: consolidate entities (merge duplicates by canonical key,
        # e.g. "Intel" + "Intel Corporation") and rewrite relationships +
        # units to point at the canonical names. Idempotent.
        rename_map = _consolidate_entities(brain)
        if rename_map:
            _apply_entity_renames(brain, rename_map)
            _debug_event(
                "store.entities.consolidated",
                "Merged duplicate entities by canonical name",
                merges=rename_map,
            )

        _write_brain(brain)
        _build_indexes(brain)

        _debug_event(
            "store.done",
            "Brain state written and indexes rebuilt",
            source_id=source_id,
            units_stored=len(stored_units),
            entities_stored=len(new_entities),
            relationships_stored=len(new_rels),
            raw_chunks_stored=len(new_raw_chunks),
            chroma_total=collection.count(),
            brain_sources=len(brain["sources"]),
            brain_units=len(brain["units"]),
            brain_raw_chunks=len(brain.get("rawChunks", [])),
        )

        return {
            "units_stored": len(stored_units),
            "units_superseded": superseded_count,
            "units_disputed": disputed_count,
            "entities_stored": len(new_entities),
            "relationships_stored": len(new_rels),
            "raw_chunks_stored": len(new_raw_chunks),
            "chroma_total": collection.count(),
            "brain_totals": {
                "sources": len(brain["sources"]),
                "entities": len(brain["entities"]),
                "units": len(brain["units"]),
                "relationships": len(brain["relationships"]),
                "rawChunks": len(brain.get("rawChunks", [])),
            },
        }


