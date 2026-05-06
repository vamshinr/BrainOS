# BrainOS

The biggest blocker to AI automation inside companies is no longer model
quality — it's domain knowledge. Every company has critical know-how
scattered across people's heads, old email threads, Slack, and support
tickets. AI agents can't operate like that.

**BrainOS** is the missing layer. It pulls knowledge out of every
fragmented source, structures it into atomic units, reconciles it as things
change, and emits an executable skill file that AI agents load directly.

Not search. Not chat-over-docs. A living map of how a company actually works.

## What it does

1. **Ingest** raw content from Slack threads, emails, support tickets, docs,
   meeting notes — paste it in, no integrations needed for the demo.
2. **Extract** atomic knowledge units across seven kinds: facts, processes,
   decisions, ownership, definitions, policies, and gotchas. Each unit is
   self-contained, has an evidence quote, and a confidence score.
3. **Reconcile** new units against existing ones. When a new ownership or
   policy supersedes an old one, the brain marks the old one stale.
4. **Map** entities (people, teams, systems, products, customers) and the
   relationships between them.
5. **Ask** grounded questions with citations.
6. **Export** as `SKILLS.md` — a self-contained file any AI agent can load
   to operate inside this company.

## Run it

```bash
cp .env.local.example .env.local
# add an AI key — AI_GATEWAY_API_KEY recommended, or OPENAI_API_KEY
npm install
npm run dev
```

Visit http://localhost:3000 and click **Seed with example company** to
load five sources (Slack, email, ticket, runbook, leadership meeting).

## Stack

- Next.js 16 App Router, React 19
- AI SDK v7 via Vercel AI Gateway (`provider/model` strings)
- Local JSON store at `data/brain.json` (swap for a DB in production)
- Zod-validated structured extraction with `generateObject`

## Architecture

```
src/lib/
  types.ts        — KnowledgeUnit, Entity, Source, BrainState
  store.ts        — JSON file persistence with serialized writes
  ai.ts           — model() via gateway, configurable via BRAINOS_MODEL
  extractor.ts    — extractFromSource(), reconcileUnit(), mergeIntoState()
  skills.ts       — generateSkills() emits the executable SKILLS.md
  seed-data.ts    — five demo sources for instant demo

src/app/api/
  ingest          — POST: extract + reconcile + persist
  ask             — POST: keyword-rank units, answer with citations
  skills          — GET: SKILLS.md (or ?format=json)
  seed            — POST: ingest the five demo sources
  state           — GET full brain, DELETE ?unit=<id> or ?all=true

src/app/
  /         — dashboard
  /ingest   — paste any source
  /graph    — entity map
  /ask      — query the brain
  /skills   — preview & download SKILLS.md
```

## Why this matters

Every company in the world will need this layer. The AI tools exist. The
BrainOS layer does not yet — until now.
