"""ExecutionAgent: 5-signal hybrid retrieval and grounded answer generation."""
from __future__ import annotations
import time
import json
from clients.router import _resolve_override
from storage.brain import _read_brain
from storage.chroma import collection
from core.logging import _debug_event, _log_call
from core.indexes import _build_indexes, _tokenize_search, _rrf_fuse
from core.temporal import _detect_temporal_intent, _unit_temporal_score
from agents.extraction import _parse_extraction_json

class ExecutionAgent:
    """Hybrid retrieval over ChromaDB, BM25, raw chunks, and brain.json graph state."""

    def revise_answer(
        self,
        query: str,
        draft_answer: str,
        context_docs: list,
        verification: dict,
        model_override: str | None = None,
    ) -> str:
        """Rewrite an answer after verifier finds unsupported or weakly grounded claims."""
        if not context_docs:
            return "The brain does not have this information yet."

        ctx = "\n".join(f"{i+1}. {d}" for i, d in enumerate(context_docs))
        unsupported = verification.get("unsupported_claims") or []
        contradictions = verification.get("contradictions") or []
        missing = verification.get("missing_aspects") or []
        prompt = (
            "Rewrite the draft answer so it is strictly supported by the retrieved context.\n\n"
            "Rules:\n"
            "1. Remove every unsupported or contradicted claim.\n"
            "2. Do not add any new names, causes, timelines, tools, services, or process details.\n"
            "3. For WHY/root-cause questions, separate directly stated causes from unknowns. "
            "Use 'The retrieved evidence states...' or 'The retrieved evidence does not explicitly state...' when needed.\n"
            "4. Cite every concrete claim with context item IDs like [1] or [2].\n"
            "5. If only raw chunks support the answer, say 'Based on source excerpt context...'.\n"
            "6. If the context is insufficient, answer exactly: 'The brain does not have this information yet.'\n"
            "7. Keep the final answer concise.\n\n"
            f"QUESTION:\n{query}\n\n"
            f"RETRIEVED CONTEXT:\n{ctx}\n\n"
            f"DRAFT ANSWER:\n{draft_answer}\n\n"
            f"UNSUPPORTED CLAIMS TO REMOVE:\n{json.dumps(unsupported)}\n\n"
            f"CONTRADICTIONS TO AVOID:\n{json.dumps(contradictions)}\n\n"
            f"MISSING ASPECTS TO ACKNOWLEDGE IF RELEVANT:\n{json.dumps(missing)}\n\n"
            "Return only the revised final answer. No JSON."
        )
        client, model = _resolve_override("execute", model_override)
        t0 = time.time()
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an evidence-constrained answer rewriter. "
                            "Your only job is to remove unsupported content and produce a concise, cited answer."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=420,
                temperature=0.0,
            )
            latency_ms = int((time.time() - t0) * 1000)
            usage = getattr(response, "usage", None)
            _log_call(
                "execute", model, latency_ms,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                note="answer_revision",
            )
            revised = response.choices[0].message.content.strip()
            _debug_event(
                "answer.revise.done",
                "Verifier-triggered answer revision complete",
                unsupported=len(unsupported),
                contradictions=len(contradictions),
                missing=len(missing),
            )
            return revised or "The brain does not have this information yet."
        except Exception as e:
            _debug_event("answer.revise.error", "Answer revision failed", error=e)
            return draft_answer

    def execute(self, query: str, n_results: int = 6, model_override: str | None = None) -> dict:
        t0 = time.time()

        brain = _read_brain()
        searchable_units = [u for u in brain.get("units", []) if u.get("id")]
        raw_chunks = [c for c in brain.get("rawChunks", []) if c.get("id") and c.get("text")]
        unit_by_id = {u["id"]: u for u in searchable_units}
        chunk_by_id = {c["id"]: c for c in raw_chunks}
        temporal_intent = _detect_temporal_intent(query)
        _build_indexes(brain)

        retrieved_ids: list[str] = []
        retrieved_docs: list[str] = []
        retrieved_metas: list[dict] = []
        retrieved_chunk_ids: list[str] = []
        retrieved_chunks: list[dict] = []
        relationship_context: list[str] = []

        query_tokens = _tokenize_search(query)
        debug = {
            "retrieval_mode": "hybrid_bm25_vector_graph",
            "temporal_intent": temporal_intent,
            "vector_unit_hits": [],
            "vector_chunk_hits": [],
            "bm25_hits": [],
            "chunk_bm25_hits": [],
            "entity_hits": [],
            "graph_hits": [],
            "final_unit_ids": [],
            "final_chunk_ids": [],
        }

        def _dedupe_ranked(ids: list[str], limit: int | None = None) -> list[str]:
            out: list[str] = []
            seen: set[str] = set()
            for item_id in ids:
                if item_id and item_id not in seen:
                    seen.add(item_id)
                    out.append(item_id)
                    if limit and len(out) >= limit:
                        break
            return out

        def _rank_debug(ids: list[str], scores: dict[str, float] | None = None, limit: int = 12) -> list[dict]:
            return [
                {"id": item_id, "score": round(float(scores.get(item_id, 0.0)), 4) if scores else None}
                for item_id in ids[:limit]
            ]

        # ── Signal 1: Chroma vector search over units + raw chunks ───────────
        vector_unit_ranked: list[str] = []
        vector_chunk_ranked: list[str] = []
        vector_unit_scores: dict[str, float] = {}
        vector_chunk_scores: dict[str, float] = {}
        chroma_total = collection.count()
        if chroma_total > 0:
            try:
                vector_results = collection.query(
                    query_texts=[query],
                    n_results=min(max(n_results * 8, 24), chroma_total),
                )
                ids = vector_results["ids"][0] if vector_results.get("ids") else []
                distances = vector_results["distances"][0] if vector_results.get("distances") else []
                metas = vector_results["metadatas"][0] if vector_results.get("metadatas") else []
                for cid, dist, meta in zip(ids, distances, metas):
                    doc_type = (meta or {}).get("doc_type", "unit")
                    similarity = max(0.0, 1.0 - float(dist or 0.0))
                    if doc_type == "raw_chunk" or cid in chunk_by_id:
                        if cid in chunk_by_id:
                            vector_chunk_ranked.append(cid)
                            vector_chunk_scores[cid] = similarity
                    else:
                        if cid in unit_by_id:
                            vector_unit_ranked.append(cid)
                            vector_unit_scores[cid] = similarity
                vector_unit_ranked = _dedupe_ranked(vector_unit_ranked, n_results * 6)
                vector_chunk_ranked = _dedupe_ranked(vector_chunk_ranked, n_results * 4)
                _debug_event(
                    "retrieve.chroma",
                    "Chroma vector query complete",
                    query=query,
                    total=chroma_total,
                    unit_hits=len(vector_unit_ranked),
                    chunk_hits=len(vector_chunk_ranked),
                )
            except Exception as e:
                _debug_event("retrieve.chroma.error", "Chroma vector query failed", query=query, error=e)

        # ── Signal 2: lexical BM25 over enriched unit text ──────────────────
        bm25_ranked: list[str] = []
        bm25_scores_by_id: dict[str, float] = {}
        if _bm25_index and _bm25_unit_ids and query_tokens:
            bm25_scores = _bm25_index.get_scores(query_tokens)
            ranked_pairs = sorted(
                zip(_bm25_unit_ids, bm25_scores), key=lambda x: x[1], reverse=True
            )[:n_results * 8]
            bm25_ranked = [uid for uid, sc in ranked_pairs if sc > 0]
            bm25_scores_by_id = {uid: float(sc) for uid, sc in ranked_pairs if sc > 0}

        # ── Signal 3: lexical BM25 over raw chunks ──────────────────────────
        chunk_bm25_ranked: list[str] = []
        chunk_bm25_scores_by_id: dict[str, float] = {}
        if _chunk_bm25_index and _chunk_ids and query_tokens:
            chunk_scores = _chunk_bm25_index.get_scores(query_tokens)
            ranked_pairs = sorted(
                zip(_chunk_ids, chunk_scores), key=lambda x: x[1], reverse=True
            )[:n_results * 6]
            chunk_bm25_ranked = [cid for cid, sc in ranked_pairs if sc > 0]
            chunk_bm25_scores_by_id = {cid: float(sc) for cid, sc in ranked_pairs if sc > 0}

        # ── Signal 4: direct entity/subject lookup ──────────────────────────
        entity_ranked: list[str] = []
        entity_scores: dict[str, float] = {}
        q_token_set = set(query_tokens)
        if _entity_index and q_token_set:
            normalized_query = " ".join(query_tokens)
            for entity_name, uid_set in _entity_index.items():
                ent_tokens = set(_tokenize_search(entity_name))
                if not ent_tokens:
                    continue
                phrase_hit = entity_name in normalized_query
                overlap = len(ent_tokens & q_token_set)
                if phrase_hit or overlap:
                    weight = 4.0 if phrase_hit else float(overlap)
                    for uid in uid_set:
                        entity_scores[uid] = entity_scores.get(uid, 0.0) + weight
            entity_ranked = sorted(entity_scores, key=lambda uid: entity_scores[uid], reverse=True)[:n_results * 6]

        # ── Signal 5: one-hop knowledge graph expansion ─────────────────────
        seed_ids = _rrf_fuse([vector_unit_ranked, bm25_ranked, entity_ranked])[:max(n_results * 2, 10)]
        seed_entities: set[str] = set()
        for uid in seed_ids:
            unit = unit_by_id.get(uid)
            if not unit:
                continue
            if unit.get("subject"):
                seed_entities.add(unit["subject"].lower())
            seed_entities.update(ent.lower() for ent in unit.get("entities", []))

        graph_ranked: list[str] = []
        graph_relationships: list[dict] = []
        if seed_entities:
            for rel in brain.get("relationships", []):
                frm = rel.get("from", "").lower()
                to = rel.get("to", "").lower()
                if frm in seed_entities or to in seed_entities:
                    graph_relationships.append(rel)
                    rel_uid = rel.get("unitId")
                    if rel_uid in unit_by_id and rel_uid not in graph_ranked:
                        graph_ranked.append(rel_uid)
                    other = to if frm in seed_entities else frm
                    for unit in searchable_units:
                        subject = unit.get("subject", "").lower()
                        entities = {ent.lower() for ent in unit.get("entities", [])}
                        if other and (subject == other or other in entities):
                            uid = unit["id"]
                            if uid not in graph_ranked:
                                graph_ranked.append(uid)
                            break

        # ── Fuse and rerank unit candidates with temporal/confidence signals ─
        source_lists = [
            (vector_unit_ranked, 2.0),
            (bm25_ranked, 1.6),
            (entity_ranked, 1.35),
            (graph_ranked, 1.0),
        ]
        fused_scores: dict[str, float] = {}
        for ranked, weight in source_lists:
            for rank, uid in enumerate(ranked):
                fused_scores[uid] = fused_scores.get(uid, 0.0) + weight / (60 + rank + 1)

        scored_ids = []
        for uid, base_score in fused_scores.items():
            unit = unit_by_id.get(uid)
            if not unit:
                continue
            confidence = float(unit.get("confidence", 0.7))
            temporal_boost = _unit_temporal_score(unit, temporal_intent)
            stale_penalty = 0.55 if unit.get("stale") or unit.get("supersededBy") else 1.0
            final_score = base_score * (0.65 + confidence) * temporal_boost * stale_penalty
            scored_ids.append((uid, final_score))
        fused_ids = [uid for uid, _ in sorted(scored_ids, key=lambda item: item[1], reverse=True)[:n_results]]

        for uid in fused_ids:
            unit = unit_by_id.get(uid)
            if not unit:
                continue
            retrieved_ids.append(uid)
            retrieved_docs.append(unit.get("statement", ""))
            retrieved_metas.append({
                "kind": unit.get("kind", "fact"),
                "confidence": float(unit.get("confidence", 0.7)),
                "subject": unit.get("subject", ""),
                "sector": unit.get("sector", "General"),
                "department": unit.get("department", "general"),
                "entities": unit.get("entities", []),
                "disputed": unit.get("disputed", False),
                "stale": unit.get("stale", False),
                "supersededBy": unit.get("supersededBy"),
                "validFrom": unit.get("validFrom"),
                "validTo": unit.get("validTo"),
                "effectiveDate": unit.get("effectiveDate"),
                "temporalStatus": unit.get("temporalStatus", "unknown"),
            })

        # ── Fuse raw chunk candidates for source-excerpt fallback ────────────
        chunk_scores: dict[str, float] = {}
        for ranked, weight in ((vector_chunk_ranked, 1.6), (chunk_bm25_ranked, 1.9)):
            for rank, cid in enumerate(ranked):
                chunk_scores[cid] = chunk_scores.get(cid, 0.0) + weight / (60 + rank + 1)
        fused_chunk_ids = [
            cid for cid, _ in sorted(chunk_scores.items(), key=lambda item: item[1], reverse=True)
            if cid in chunk_by_id
        ][:3]
        for cid in fused_chunk_ids:
            chunk = chunk_by_id.get(cid)
            if not chunk:
                continue
            retrieved_chunk_ids.append(cid)
            retrieved_chunks.append(chunk)

        seen_rels: set[str] = set()
        for rel in graph_relationships[: max(3, n_results)]:
            rel_id = rel.get("id") or f"{rel.get('from')}:{rel.get('relation')}:{rel.get('to')}"
            if rel_id in seen_rels:
                continue
            seen_rels.add(rel_id)
            relationship_context.append(
                f"{rel.get('from', '')} {rel.get('relation', '')} {rel.get('to', '')}"
            )

        debug.update({
            "vector_unit_hits": _rank_debug(vector_unit_ranked, vector_unit_scores),
            "vector_chunk_hits": _rank_debug(vector_chunk_ranked, vector_chunk_scores),
            "bm25_hits": _rank_debug(bm25_ranked, bm25_scores_by_id),
            "chunk_bm25_hits": _rank_debug(chunk_bm25_ranked, chunk_bm25_scores_by_id),
            "entity_hits": _rank_debug(entity_ranked, entity_scores),
            "graph_hits": _rank_debug(graph_ranked),
            "final_unit_ids": retrieved_ids,
            "final_chunk_ids": retrieved_chunk_ids,
        })

        _debug_event(
            "retrieve.hybrid",
            "Hybrid BM25 + vector + graph retrieval complete",
            query=query,
            temporal_mode=temporal_intent.get("mode"),
            target_date=temporal_intent.get("target_date"),
            searchable_units=len(searchable_units),
            raw_chunks=len(raw_chunks),
            vector_unit_hits=len(vector_unit_ranked),
            vector_chunk_hits=len(vector_chunk_ranked),
            bm25_hits=len(bm25_ranked),
            chunk_bm25_hits=len(chunk_bm25_ranked),
            entity_hits=len(entity_ranked),
            graph_hits=len(graph_ranked),
            relationships=len(relationship_context),
            final_unit_ids=",".join(retrieved_ids),
            final_chunk_ids=",".join(retrieved_chunk_ids),
        )

        # Code-map context — surfaces entity↔path links, symbol locations,
        # and module summaries when the question touches a code source. Cheap
        # (in-memory scan over the codebase blocks) and runs even when no
        # facts/chunks are retrieved, so a code-only question still gets help.
        code_context_lines = _code_context_for_query(query, brain)

        if retrieved_docs or retrieved_chunks or code_context_lines:
            context_lines = []
            disputed_facts = []
            if retrieved_docs:
                context_lines.append("Facts:")
            for i, (uid, doc, m) in enumerate(
                zip(retrieved_ids, retrieved_docs, retrieved_metas), 1
            ):
                u = unit_by_id.get(uid, {})
                tags = []
                if u.get("disputed"):
                    tags.append("DISPUTED")
                    disputed_facts.append(i)
                if u.get("stale") or u.get("supersededBy"):
                    tags.append("SUPERSEDED")
                tag_str = f" [{', '.join(tags)}]" if tags else ""
                dept = m.get("department", "")
                dept_str = f" ({dept})" if dept and dept != "general" else ""
                temporal_bits = []
                if m.get("temporalStatus"):
                    temporal_bits.append(f"status:{m.get('temporalStatus')}")
                if m.get("effectiveDate"):
                    temporal_bits.append(f"effective:{m.get('effectiveDate')}")
                if m.get("validFrom"):
                    temporal_bits.append(f"valid_from:{m.get('validFrom')}")
                if m.get("validTo"):
                    temporal_bits.append(f"valid_to:{m.get('validTo')}")
                temporal_str = f" [{', '.join(temporal_bits)}]" if temporal_bits else ""
                context_lines.append(f"F{i}.{tag_str}{dept_str}{temporal_str} {doc}")
            if relationship_context:
                context_lines.append("\nGraph relationships:")
                for i, rel_text in enumerate(relationship_context, 1):
                    context_lines.append(f"R{i}. {rel_text}")
            if retrieved_chunks:
                context_lines.append("\nRaw source excerpts:")
                for i, chunk in enumerate(retrieved_chunks, 1):
                    source_title = chunk.get("sourceTitle") or chunk.get("sourceId", "source")
                    text = chunk.get("text", "")
                    if len(text) > 1800:
                        text = text[:1800] + "..."
                    context_lines.append(
                        f"C{i}. [{source_title} chunk {chunk.get('chunkIndex')}] {text}"
                    )
            if code_context_lines:
                context_lines.append("\nCode map:")
                for i, code_text in enumerate(code_context_lines, 1):
                    context_lines.append(f"K{i}. {code_text}")
            context_section = "\n".join(context_lines)

            disputed_note = ""
            if disputed_facts:
                disputed_note = (
                    f"\nFacts {disputed_facts} are DISPUTED — multiple sources contradict. "
                    f"If your answer relies on them, explicitly call out the conflict.\n"
                )

            user_prompt = (
                f"Retrieved company knowledge:\n"
                f"{context_section}\n{disputed_note}\n"
                f"Question: {query}\n"
                f"Answer:"
            )
            system_msg = (
                "You are a company knowledge assistant. Rules:\n"
                "1. Use ONLY the Facts, Graph relationships, Raw source excerpts, and Code map entries above. Never invent names, services, or numbers.\n"
                "2. Facts are the primary source. Raw source excerpts and Code map entries are fallback evidence when extracted facts are missing or incomplete.\n"
                "3. If you rely on a raw source excerpt or code-map entry because no fact covers the answer, say the answer is based on that source.\n"
                "4. Cite every concrete claim inline with the evidence ID that supports it, using F1, R1, C1, or K1 labels.\n"
                "5. Do not turn implications into facts. If a causal link is not explicitly stated, say the retrieved evidence does not explicitly state it.\n"
                "6. For WHY/root-cause/incident questions, only name causes that the context directly states as causes. Do not add deployment, infra, or process assumptions.\n"
                "7. Always name the specific person, team, or system only when the context names them. Never say 'the company' or 'someone'.\n"
                "8. Prefer fresh facts; ignore facts marked SUPERSEDED unless the user explicitly asks about historical state.\n"
                "9. For time-sensitive questions, use status/effective/valid_from/valid_to metadata. "
                "For 'now/current' questions, prefer current or unknown facts over future/historical facts. "
                "For future or historical questions, use the facts matching that date.\n"
                "10. If facts are marked DISPUTED, say so plainly: \"The sources disagree — A says X, B says Y.\"\n"
                "11. If the retrieved context does not answer the question, reply exactly: 'The brain does not have this information yet.'\n"
                "12. Be brief. One to three sentences unless the user asks for detail."
            )
        else:
            user_prompt = f"Question: {query}"
            system_msg = (
                "The company brain has no relevant retrieved knowledge. "
                "Reply exactly: 'The brain does not have this information yet.'"
            )

        client, model = _resolve_override("execute", model_override)
        t1 = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the BrainOS execution agent running on an AMD MI300X GPU. "
                        "Answer questions strictly based on company knowledge provided in context. "
                        "Never invent facts. Never add software-engineering explanations that are not explicitly supported.\n\n"
                        "Format your response as:\n"
                        "1. A direct answer in 1-3 sentences with inline citations like [F1], [C2], or [R1].\n"
                        "2. A 'Sources:' bullet list citing each evidence item you used.\n"
                        "If the knowledge only partially covers the question, say explicitly "
                        "what is and is not covered."
                    ),
                },
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=512,
            temperature=0.1,
        )
        exec_latency_ms = int((time.time() - t1) * 1000)
        usage = getattr(response, "usage", None)
        _log_call(
            "execute", model, exec_latency_ms,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            note=f"q={query[:40]!r}",
        )

        answer = response.choices[0].message.content
        latency_ms = int((time.time() - t0) * 1000)

        return {
            "answer": answer,
            "retrieved_ids": retrieved_ids,
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "retrieved_docs": (
                retrieved_docs
                + [f"[graph] {rel}" for rel in relationship_context]
                + [
                    f"[raw chunk:{chunk.get('id')}] {chunk.get('text', '')[:1000]}"
                    for chunk in retrieved_chunks
                ]
                + code_context_lines
            ),
            "latency_ms": latency_ms,
            "retrieval_mode": "hybrid_bm25_vector_graph",
            "retrieval_debug": debug,
            "verification_context": (
                retrieved_docs
                + [f"[graph] {rel}" for rel in relationship_context]
                + [
                    f"[raw chunk:{chunk.get('id')}] {chunk.get('text', '')[:1000]}"
                    for chunk in retrieved_chunks
                ]
                + code_context_lines
            ),
        }


