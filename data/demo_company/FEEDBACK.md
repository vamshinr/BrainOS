# Feedback plan — what to collect, how, and from whom

We've been told twice by Tom Blomfield and once by Garry that the *real* product risk for a "company brain" is not the model quality — it's whether the structure we extract matches how teams actually think. The only way to learn that is feedback. This file lays out **what to collect**, **the mechanisms to collect it**, and **the questions you should not ask.**

---

## 1. What we actually need to learn (in priority order)

| # | Question | Why it matters | Who answers it |
|---|---|---|---|
| 1 | Are the **units atomic and useful as agent rules**, or are they just sentences split badly? | Determines whether SKILLS.md is load-bearing or theatre. | Engineers who have used Claude Skills / Cursor rules before. |
| 2 | Did the brain **catch a supersession or conflict** that surprised the user? | The wow moment that justifies the graph. | Anyone who's been at the company > 6 months. |
| 3 | Did the **gap analysis** surface something the user did not know was missing? | Proves the brain produces *new* knowledge, not just retrieves existing. | Operations / leadership users. |
| 4 | Did the user **trust** the answer enough to act on it? | If no, no one will plug their company into us. | Frontline workers (CX, Ops). |
| 5 | Was the **multimodal extraction** worth it, or could text-only have done 90% of the job? | Whether the AMD MI300X co-resident-VLM story is real or a flex. | Anyone, but especially the people who own the diagrams. |
| 6 | What did the user **want to ingest** that we couldn't (Loom transcripts, Linear, Salesforce, ...)? | Roadmap for connectors. | Everyone. |

These six questions are the bar. If you walk away from the hackathon without learning at least four of them, the demo failed regardless of the score.

---

## 2. Three feedback channels — different audiences, different signals

### 2.1 Per-answer thumbs (live, in-product)

**Status:** not yet built. Recommended pre-demo build (~2 hours):

- Add 👍 / 👎 buttons next to each answer in `/ask`.
- 👎 opens a 200-char text field: *"What did the brain miss or get wrong?"*
- POST to a new `/api/feedback` endpoint that appends to `data/feedback_log.jsonl`:
  ```json
  {
    "ts": "...", "query": "...", "answer": "...", "verdict": "down",
    "comment": "...", "retrieved_unit_ids": [...], "feedback_confidence": 0.78
  }
  ```
- The retrieved unit IDs and confidence are already in the response — keep them so we can correlate signal type to verdict later.

**Why this and not 5-star ratings:** binary verdicts get answered. Stars get ignored. The text field is optional, but the verdict is one click.

**What you do with it:** every Friday, scan the 👎 entries. Categorize: *missing fact*, *wrong fact*, *right fact wrong wording*, *bad citation*, *temporal miss*, *gap mistake*. The category distribution is your roadmap.

### 2.2 Post-demo card (paper or Google Form, 60 seconds)

Hand this to every judge / observer immediately after the demo, before they walk away:

```
1. Which moment, if any, surprised you? (one line)
2. Which moment felt like vapor / a stretch? (one line)
3. Would you put this in front of a real ops lead at your company? Yes / Maybe / No, because ___
4. What's the one thing you would build before showing this to anyone else?
5. Optional: name + email if we can follow up.
```

**Why these questions:** "did you like it" gets you "yeah cool", which is useless. "What surprised you" forces them to recall a specific moment and gives you a signal worth a hundred yes/no answers.

Track responses in `data/feedback_log.jsonl` too — same file, different `kind` field.

### 2.3 30-min design-partner call (post-hackathon)

Whoever fills out section 5 of the card with an email — book them for a 30 minute call. Goal: walk them through ingesting *their* data, not Helix Outdoor's. The questions that matter:

1. What's the first agent task you'd actually trust this with — refund routing, on-call escalation, deal-desk triage, something else?
2. What would have to be true for the answer to that question to be a *yes, today*?
3. Who else at your company would care about this if you sent them the demo?

The third question is the wedge. If they can't name three people, you don't have a customer.

---

## 3. Telemetry that's already in the codebase (don't re-instrument)

These are already logged — pipe them into `data/feedback_log.jsonl` instead of re-collecting:

- **`/api/metrics` recent_calls ring buffer** (last 80 LLM calls) — has task, model, latency, prompt/completion tokens, success flag, note. The per-task latency profile is gold.
- **FeedbackAgent verdicts** — every `/ask` already produces `{grounded, confidence, partial, raw_chunk_only, unsupported_claims, missing_aspects, contradictions}`. Aggregate this server-side over the demo run; that's a *self-report* of the brain's own quality.
- **Verifier-revision rate** — `answer_revised: true` in the response. If >30% of answers got revised, your extraction is leaving claims the verifier can't ground; this is a signal to tune the extraction prompt, not the answerer.
- **Gap-analysis output** — `/api/analyze/gaps` returns counts by severity. Track `(severity_distribution, pre_seed_count, post_seed_count)` per demo run.
- **Per-source extraction yield** — already logged via `_debug_event("extract.text.done", ...)`. Compute `units_extracted / chars_processed` per source kind. PDFs vs Slack vs images yield wildly different ratios; this tells you where the extractor is weak.

A useful report at the end of every demo:
```
Demo run 2026-05-09 14:30 UTC
- Sources ingested: 10
- Units stored: 113 | superseded: 6 | disputed: 2
- /ask queries: 12 | grounded: 11 | revised: 2 | "brain does not have": 1
- Gap analysis: 4 high / 1 medium / 1 low
- Avg answer latency: 1.34s | extraction p95: 4.2s
- Judge feedback: 3 👍, 1 👎 ("the diagram extraction was hit-or-miss")
```

If you put one slide in a deck after the hackathon, it's that one.

---

## 4. Questions to *not* ask

- **"Was it useful?"** — too vague. Always returns "yes, kind of."
- **"Would you pay for it?"** — at this stage no one will say yes truthfully and you'll convince yourself you have product-market fit.
- **"What features should we build next?"** — invites everyone to design a Christmas tree. Better: "what's the *one thing* that's blocking you from showing this to the rest of your team?"
- **"On a scale of 1-10..."** — averages everything to a 7. Useless.
- **"Did you find any bugs?"** — narrows attention to surface defects and away from the conceptual question (does the brain *match how I think*).

---

## 5. The two-week feedback ritual (after the hackathon)

If you keep building, this is the rhythm:

- **Daily** — review every 👎 from the in-product widget. Acknowledge or close-as-known. Don't let them pile up; the signal decays.
- **Weekly** — categorize the verdicts (see 2.1). One slide of category counts. Did our biggest category change after the last release?
- **Bi-weekly** — review every disputed unit and every gap-analysis output. Are humans actually resolving them, or is the brain accumulating noise?
- **Monthly** — pick five queries that the brain answered "I don't have this information" to. For each, decide: **(a)** ingest the missing source and verify, **(b)** mark out-of-scope on purpose, or **(c)** add it to the connector roadmap. This turns "I don't know" from a polite refusal into a working feedback loop.

The active-learning loop in the pitch ("the brain asks the company on Slack when confidence is low") is just an automated version of step (a). Build that *after* you've done it manually for a month and learned what kinds of asks land vs annoy.
