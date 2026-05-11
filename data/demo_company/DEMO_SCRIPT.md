# Helix Outdoor — 90-second demo script

> **Goal:** in 90 seconds, prove BrainOS does five things RAG can't:
> directed-graph navigation, supersession, multimodal extraction, knowledge-gap detection, and agent-shaped output.
>
> **Audience:** AMD hackathon judges, mostly engineers, will be skeptical of yet-another-RAG framing.

---

## Pre-demo checklist (the 5 minutes before you click record)

- [ ] Backend: `./src/python_backend/venv/bin/python src/python_backend/main.py` running on port 8081
- [ ] Frontend: `npm run dev` running on port 3000
- [ ] vLLM endpoints reachable (check `/metrics` page tile shows green AMD MI300X stats)
- [ ] Brain is **empty** — visit `/`, click *Reset* if not
- [ ] Demo files staged: `data/demo_company/` open in a Finder window for drag-drop
- [ ] Browser tabs open in this order: `/` (dashboard) → `/ingest` → `/graph` → `/ask` → `/skills`
- [ ] Have a Claude Code or Cursor window open in another monitor, ready to paste the SKILLS.md export

---

## The script

### 0:00–0:10 — Frame the problem (you, on camera or v/o)

> "Every company has a hidden second corpus — the one that lives in Slack threads, factory whiteboards, contract PDFs, and three people's heads. AI agents can't operate on that today. **BrainOS is the missing layer.** Let me show you with a real ops scenario."

### 0:10–0:30 — Cold ingest (10 sources, 4 file types)

Click `/ingest`. Show three tabs (Text · File · Image). Drag from `data/demo_company/`:

- **Text tab** — paste 4 of the 10 Slack/email files. While they're processing, narrate: *"Slack threads, internal email — 4 sources."*
- **File tab** — upload the 3 PDFs and 2 DOCX files. Narrate: *"contracts, policies, vendor risk reports — 5 files, mixed format."*
- **Image tab** — upload the architecture diagram, the QC whiteboard, and the org chart. Narrate: *"a diagram, a whiteboard photo, an org-chart screenshot — the LLaVA VLM running on the same MI300X reads them."*

Switch to `/`. Stat tiles tick up: ~10 sources, ~50 entities, ~30+ relationships, 100+ knowledge units. Show the colored badges (process, policy, ownership, gotcha).

### 0:30–0:40 — Graph view (the "this isn't RAG" moment)

Click `/graph`. Pan around. Point to:

> *"Real verbs. Cara Bennett `--csm_assigned-->` Camp Cosmos. Saigon TexCo `--depends-on-->` YKK Vietnam. The brain extracted these directly from Slack and a contract PDF. RAG sees text; this is structure."*

### 0:40–1:05 — Three /ask queries (the meat)

Open `/ask`. Three queries, fast.

**Query 1 (graph + escalation):**
> *"Camp Cosmos is threatening to churn over the zipper issue. Who do I escalate to right now?"*

Answer cites: `[F]` Cara Bennett is CSM, `[R]` customer→escalation edge, `[F]` Diego's email. Confidence 0.9+. Latency 1-2s on MI300X.

> Narration: *"That's a graph walk — Camp Cosmos → CSM → escalation chain. RAG can't do that."*

**Query 2 (supersession):**
> *"What's the maximum refund a CX Lead can issue without approval today?"*

Answer: $1,000 per Bruno's memo. The OLD $2,000 unit is shown with a `[SUPERSEDED]` badge and `validTo: 2026-05-01`.

> Narration: *"The old policy is in the brain — but flagged historical. RAG keeps both and hallucinates."*

**Query 3 (multimodal):**
> *"Looking at the architecture diagram, what's the most fragile webhook in the system?"*

Answer: ShipBob inventory webhook. Cites the diagram annotation (extracted by the VLM) AND Jin Ahn's Slack on the actual bug.

> Narration: *"The VLM read the diagram. The text extractor read the Slack. The graph fused them. One answer."*

### 1:05–1:15 — Gap analysis (the punch list)

Back to `/`. Click *Run gap analysis*. Modal opens with a punch list:

- HIGH: VP Operations vacant — 4 supplier units have no current owner
- HIGH: AMD Developer Cloud has no documented owner
- HIGH: Bandung Crafted has no signed MSA (verbal-only)
- MEDIUM: New factory onboarding process is paused with no owner
- OPEN DISPUTE: Trail Club 60-day vs Returns Policy 30-day

> Narration: *"This is the brain telling the company what it doesn't know about itself. There is no document that contains this list. RAG cannot produce it."*

### 1:15–1:30 — The agent loop (the close)

Click `/skills`. Show the per-department dropdown. Pick *Operations*. Show the Agent Rules block:

```markdown
- Policy constraint: ShipBob webhook - missing signature MUST 400 + PagerDuty
- Check before acting: Lot 24-A-118 - DO NOT restock; full refund, no return required
- Route ownership questions for Saigon TexCo: Marco Ferraro (acting since Apr 12)
- Follow process: Refund authority - CX Lead limit is $1,000 effective May 1, 2026
```

Click *Copy*. Paste into a fresh Claude Code session. Type:

> *"Open a PR to bump the ShipBob inventory webhook timeout to 30s."*

Claude responds: tags Jin Ahn + Sai Krishnan as reviewers (two-engineer rule), refuses to wrap signature verification in try/except (gotcha), references the runbook, references Lot 24-A-118 because it's relevant context.

> Closing line: *"Five minutes from a cold codebase to an AI agent that knows the company. That's a company brain. Built on AMD MI300X. Open source. Ready for the next 99 companies."*

---

## Backup queries (if a judge says "what about X")

- "What was the CX Lead refund limit in April 2026?" — proves time-travel
- "If a German Helix Trail Club VIP wants to return a jacket 45 days after delivery, what window applies?" — proves 3-way policy composition
- "Are we enrolled in the AMD AI Developer Program?" — proves the brain says "I don't know" instead of hallucinating
- "Show me the retrieval diagnostics for the last query" — proves the 5-signal hybrid retrieval is real (not a vibe)

---

## What can go wrong on stage and how to recover

| Failure | Recovery |
|---|---|
| VLM endpoint times out on the diagram | Skip image ingest, use the pre-seeded backup brain (`data/brain.json.helix.backup`). Narrate: "for time we'll use a pre-warmed brain." |
| Extraction returns 0 units on a chunk | The auto-retry will fire (visible in `/metrics` recent calls). If it still fails, drop that one source and continue. |
| `/ask` returns "brain does not have this information" | Good — that's the correct behavior for an empty brain. Make a joke about how RAG would hallucinate here. |
| Gap analysis modal is empty | You forgot to ingest the org-chart pin (which contains the VACANT VP Ops fact). Re-paste the text. |

---

## After the demo — collect feedback

Hand the judge a 1-minute feedback card with the questions in `FEEDBACK.md`. Do **not** ask "did you like it?" — ask the specific things in the card. Five judges × five answers each = the most useful learning signal you'll get all month.
