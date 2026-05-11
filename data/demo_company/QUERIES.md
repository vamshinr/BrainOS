# Demo /ask queries — Helix Outdoor

Each query is paired with the **capability it demonstrates** and the **expected answer shape**. Pick 5–6 of these for the live demo; keep the others as a back-pocket bench for judges who poke at it.

The queries are deliberately ordered so each one goes *one notch* further than RAG could:
exact retrieval → graph walk → temporal awareness → conflict surfacing → multimodal grounding → gap detection → agent skills export.

> **How to read this file:** every query lists the **signal** it forces (vector / BM25 / entity / graph / multimodal / gap), the **expected behavior** (so you can verify the brain is working), and the **why-not-RAG** explanation (so you can narrate it to the judge in 1 sentence).

---

## Tier 1 — Direct retrieval (warm-up; RAG can do this too)

### Q1. "What is the standard return window for a physical product at Helix Outdoor?"
- **Signal**: vector + BM25 (units), straightforward.
- **Expected**: "30 days from delivery date for unused product per Returns Policy v2.1, citing `[F1]`."
- **Why this matters**: baseline grounding works. Judge sees inline `[F1]` citation + grounded badge + retrieval debug pane.

### Q2. "Who owns the Saigon TexCo factory relationship right now?"
- **Signal**: entity index hit on "Saigon TexCo".
- **Expected**: "Marco Ferraro is the acting owner since Maya Lin departed April 12, 2026 — see the org-chart pin and Diego's coverage memo." Cites the Slack pin and Diego's memo. **Should not** hallucinate "Maya Lin" as the current owner.
- **Why-not-RAG**: a naive RAG over the MSA PDF would say "Maya Lin" because that's the signed name on the contract. The brain *supersedes* with the more recent Slack post.

---

## Tier 2 — Graph navigation (RAG can't do this)

### Q3. "Camp Cosmos is threatening to churn over the zipper issue. Who do I escalate to right now?"
- **Signal**: graph walk — start at customer "Camp Cosmos" → CSM edge (Cara Bennett) → escalation edges (Diego Marin, Camille Rousseau, Bruno Castelli) → context: defective lot 24-A-118.
- **Expected**: "Camp Cosmos's CSM is Cara Bennett. Per the SLA matrix and Diego's email of May 6, escalations on this account go to Diego Marin (CEO) directly, with Camille Rousseau notified for company-level apology and Bruno Castelli prepped for credit. Brian Wallace is the customer's contact." Cites `[F]` for the SLA, `[R]` for the customer→CSM edge, `[F]` for the email.
- **Why-not-RAG**: a vector store would surface 5 docs that mention Camp Cosmos and dump them. The brain *traverses the graph* and assembles a single coherent escalation path.

### Q4. "If a wholesale customer raises a defective-lot complaint at midnight UTC, who has to be notified within the hour?"
- **Signal**: graph walk + policy lookup.
- **Expected**: "Cara Bennett (CX-B2B Lead) and Marco Ferraro (factory liaison) per the SLA Matrix v2.0. Strategic Wholesale customers (Camp Cosmos, TrekRight, REI test pilot) additionally get Diego Marin." Cites SLA matrix + escalation rules.
- **Why-not-RAG**: the answer requires composing two facts (defective-lot rule + tier escalation chain) that live in two different documents (one DOCX, one PDF, one Slack). RAG might surface either but rarely both, and won't synthesize.

---

## Tier 3 — Temporal awareness / supersession (RAG silently keeps both)

### Q5. "What's the maximum refund a CX Lead can issue without approval today?"
- **Signal**: temporal intent = current; supersession penalty.
- **Expected**: "$1,000 per Bruno Castelli's memo of April 28, 2026 (effective May 1). The previous limit of $2,000 is **superseded** and applies only to refunds processed before May 1." Marks the old PDF unit `[SUPERSEDED]`.
- **Why-not-RAG**: a vector store retrieves both the PDF "$2,000" and the email "$1,000" with no recency awareness and the LLM averages or picks randomly. The brain hard-flags one as historical.

### Q6. "What was the CX Lead refund limit in April 2026?"
- **Signal**: temporal intent = historical; the brain *prefers* the old fact for this question.
- **Expected**: "$2,000 per the v2.1 Returns Policy. This was reduced to $1,000 effective May 1, 2026."
- **Why-not-RAG**: most RAG can't time-travel. The brain's `_unit_temporal_score()` actively boosts historical/expired units when the question contains "previously / before / Q1 / <month> 20XX".

### Q7. "What's the lead time for a Trailspire 40L PO right now?"
- **Signal**: supersession of MSA PDF clause by Slack memo.
- **Expected**: "28 days for nylon SKUs as of May 2026, per Marco Ferraro's operational memo. The Master Supply Agreement (signed Oct 2024) lists 21 days but that has not been achievable since the Tet 2026 holiday — the parties are operating under a verbal interim until the November renewal."
- **Why-not-RAG**: the MSA PDF is more "authoritative-looking" than a Slack message — a RAG would over-weight it. The brain supersedes based on date + temporal cues ("has not been achievable since", "until renewal").

---

## Tier 4 — Conflict surfacing (RAG hallucinates; brain says "they disagree")

### Q8. "What is the EU customer return window for digital products?"
- **Signal**: reconciliation flagged as `supersedes`, both kept with the old marked superseded.
- **Expected**: "14 days for EU customers on digital products per Priya Iyer's legal note of April 30, 2026. This **supersedes** the 7-day rule in the v2.1 Returns Policy section 4.2 — but only for EU customers; the 7-day rule still applies to non-EU."
- **Why-not-RAG**: the brain *calls out* that this overrides another policy. RAG would return both with no distinction.

### Q9. "If a German Helix Trail Club VIP customer wants to return a physical jacket 45 days after delivery, what window applies?"
- **Signal**: 3-way policy composition (VIP rule + EU rule + standard rule + tier order).
- **Expected**: "60 days, per Camille's note of May 1 — Helix Trail Club members get the longest applicable window. The EU 14-day rule is for *digital* products; the 30-day standard is for non-VIP. Take the longest." Cites all three.
- **Why-not-RAG**: requires reasoning over three rules from three different sources (Slack, PDF, legal email). The brain has them all as atomic units with explicit `entities` overlap.

---

## Tier 5 — Multimodal extraction (RAG doesn't see images at all)

### Q10. "Looking at the architecture diagram, what's the most fragile webhook in the system?"
- **Signal**: VLM extraction of "ShipBob → Backend webhook" + the inline annotation about signature verification + Jin Ahn's Slack thread.
- **Expected**: "The ShipBob → Backend inventory webhook. The diagram is annotated 'Missing X-Shipbob-Signature → 400 + PagerDuty alert' (Sai Krishnan / Jin Ahn). Jin's Slack on May 2 documents a real bug: ShipBob occasionally drops the signature header during their nightly maintenance window (2-4am UTC Tuesdays), and a prior version of the handler silently 200-OK'd those requests. Two-engineer review is now required on the handler."
- **Why-not-RAG**: this answer literally cannot exist without VLM extraction of the architecture diagram fused with the text-extracted Slack gotcha. Pure-RAG-over-text would miss the diagram entirely.

### Q11. "What are the QC checks for a Trailspire 40L before it ships?"
- **Signal**: VLM extraction of the QC whiteboard photo.
- **Expected**: 7-point list (zipper test x10 cycles, stitching density 8 spi min, logo placement within 2mm, lot tag verification, hardware torque, water-bottle elastic, desiccant pack), with the YKK-only constraint and the Lot 24-A-118 defective callout. Cites the whiteboard photo as the source.
- **Why-not-RAG**: hand-written/whiteboard knowledge that no document captures.

---

## Tier 6 — Knowledge gap detection (RAG can't do this at all)

### Q12. "Run gap analysis. What is Helix Outdoor missing?"
- **Signal**: deterministic graph scan via `/api/analyze/gaps`.
- **Expected**: at least 5 items —
    - **HIGH**: VP Operations role vacant (org chart says VACANT, 4 supplier-related units lack a current owner).
    - **HIGH**: AMD Developer Cloud has no documented owner (vendor risk report flagged it; Tomas's Slack confirms).
    - **HIGH**: Bandung Crafted has no signed MSA (verbal-only relationship from the departed VP).
    - **MEDIUM**: New factory onboarding process is paused and has no current owner.
    - **OPEN DISPUTE**: Trail Club 60-day window vs Returns Policy 30-day window (resolved by "longest wins" rule but the documents themselves disagree).
- **Why-not-RAG**: requires graph topology analysis. There is no document that says "we have a gap here" — the gap is the *absence* of a document.

### Q13. "Are we enrolled in the AMD AI Developer Program?"
- **Signal**: explicit gap path (the brain has Tomas's Slack mentioning the question but no answer).
- **Expected**: "The brain does not have this information yet — Tomas Becker raised this question in #general on May 4, 2026 but no follow-up has been ingested. Sai Krishnan and Bruno Castelli were tagged. Recommend confirming with AMD vendor account."
- **Why-not-RAG**: a RAG would hallucinate "yes" or "no" from adjacent context. The brain knows when to say "I don't know" *and* tells you who to ask.

---

## Tier 7 — Skills export (the closing demo)

### Q14. (no /ask, click *Export → SKILLS.md* and inspect)
- **Expected**: a Markdown file with `Scope`, `When To Use`, `Current Operational Facts`, `Ownership And Routing`, `Policies`, `Processes`, `Gotchas`, `Decisions`, `Temporal Notes`, `Agent Rules`, `Knowledge Graph Relationships`, `Source Index`.
- The **Agent Rules** section should include things like:
    - `- Policy constraint: ShipBob webhook - A missing X-Shipbob-Signature header MUST be rejected with HTTP 400 and a PagerDuty alert; never silently dropped.`
    - `- Check before acting: Lot 24-A-118 - Trailspire 40L units from Lot 24-A-118 must not be restocked; full refund + 20% discount, no return required.`
    - `- Route ownership questions for Saigon TexCo using this fact: Marco Ferraro is the acting owner since Maya Lin departed April 12, 2026.`
    - `- Follow process: Refund authority - CX Lead refund limit is $1,000 effective May 1, 2026.`
- **Why this closes the demo**: drop the file into a Claude Code session. Ask "open a PR to bump the ShipBob webhook timeout to 30s." Claude reads the SKILLS.md, knows the two-engineer rule, knows not to wrap signature verification in try/except, knows to tag Jin Ahn and Sai Krishnan as reviewers.

---

## Recommended demo running order (5 queries, ~3 minutes)

1. **Q3** (graph escalation — wow moment, hard for RAG)
2. **Q5** (supersession of refund limit — visible `[SUPERSEDED]` badge in the response)
3. **Q10** (multimodal — diagram + Slack synthesized into one answer)
4. **Q12** (gap analysis — punch list of unknowns)
5. **Q14** (SKILLS.md export → drop into Claude Code → 1 minute live agent demo)

Then keep Q4, Q7, Q9, Q13 as on-demand follow-ups for judge questions.
