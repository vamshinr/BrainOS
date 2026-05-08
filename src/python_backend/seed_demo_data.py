"""
BrainOS Seed Data Generator
============================
Generates a rich, realistic company knowledge base for demo purposes.
Includes: ownership chains, policy conflicts, cross-references, escalation paths,
deprecated knowledge, multi-hop relationships, and gap-triggering edge cases.

Run: python generate_seed_data.py
Output: data/mock_sources.json + data/knowledge_graph.json
"""

import json
import os
import uuid
from datetime import datetime, timedelta
import random

random.seed(42)

def ts(days_ago=0, hours_ago=0):
    """Generate ISO timestamp relative to now."""
    dt = datetime(2026, 5, 7, 12, 0, 0) - timedelta(days=days_ago, hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def entry(source_type, author, content, days_ago=0, hours_ago=0, tags=None, supersedes=None, confidence=1.0):
    return {
        "id": str(uuid.uuid4()),
        "source_type": source_type,
        "author": author,
        "content": content,
        "timestamp": ts(days_ago, hours_ago),
        "tags": tags or [],
        "supersedes": supersedes,
        "confidence": confidence,
    }


# ─────────────────────────────────────────────
# PEOPLE & ORG CHART  (gives the graph its edges)
# ─────────────────────────────────────────────

ORG_CHART = [
    entry("notion", "HR System", """
COMPANY ORG CHART — Updated May 2026

Executive Team:
- CEO: Jordan Blake  (jordan@company.com)
- CTO: Carol Singh   (carol@company.com)
- CFO: Marcus Webb   (marcus@company.com)
- VP Sales: [VACANT — Sarah Chen departed April 2026]
- VP Product: Priya Nair (priya@company.com)

Engineering (reports to CTO Carol Singh):
- Engineering Manager: David Lee (david@company.com)
- Platform Lead: Sam Torres (sam@company.com)
- Security Lead: Fatima Al-Rashid (fatima@company.com)
- ML Lead: Rajan Mehta (rajan@company.com)
- Senior Engineers: Kai Okonkwo, Yuki Tanaka, Bruno Ferreira

Customer Success (reports to CEO temporarily, was under VP Sales):
- Head of CS: Alice Chen (alice@company.com) — ACTING VP Sales duties for accounts <$50k ARR
- Support Leads: Preet Kaur, Miguel Reyes
- Enterprise Accounts (>$50k ARR): Dave Okafor (dave@company.com) — TEMPORARY until new VP Sales joins

Finance (reports to CFO Marcus Webb):
- Finance Lead: Dave Okafor (dave@company.com) — NOTE: Dave covers both Finance and temp Enterprise Accounts
- AP/AR: Elena Vasquez (elena@company.com)

Legal & Compliance:
- General Counsel: Nadia Petrov (nadia@company.com)
- Compliance: [outsourced to Thornfield Partners]

IMPORTANT: With Sarah Chen's departure, all enterprise contracts >$50k ARR must be co-signed
by Dave Okafor (Finance) AND Jordan Blake (CEO) until new VP Sales is onboarded.
""", days_ago=2, tags=["org_chart", "ownership", "enterprise", "contracts"]),

    entry("slack", "Dave Okafor", """
#general — pinned message

Hey everyone — just to clarify the current situation with enterprise accounts now that 
Sarah is gone. Until the new VP Sales joins (expected June 15):
- Deals <$50k ARR → Alice Chen handles
- Deals $50k–$200k ARR → me (Dave) handles, needs Marcus approval for discounts
- Deals >$200k ARR → escalate directly to Jordan (CEO), cc me and Nadia (Legal)

Please do NOT promise any SLAs to enterprise clients without checking with Alice first 
on what we can actually deliver right now. We're stretched thin.
""", days_ago=5, tags=["ownership", "enterprise", "escalation", "sales"]),
]

# ─────────────────────────────────────────────
# REFUND & BILLING POLICY (includes a conflict + supersession)
# ─────────────────────────────────────────────

REFUND_POLICY = [
    entry("notion", "Alice Chen", """
REFUND POLICY v2.1 — Effective March 1, 2026
Owner: Alice Chen (Head of CS)
Approved by: Marcus Webb (CFO)

Standard Refunds:
- Unused product, request within 30 days → automatic approval via Stripe portal
- Partially used, within 30 days → 50% refund, requires Support Lead approval
- Any request 31–90 days → manual review, requires Alice Chen approval
- Requests >90 days → denied by default, escalate to Marcus Webb if customer is Enterprise tier

Double-Charge Policy:
- Any verified double-charge → full refund, no questions, process within 24 hours
- Use Stripe Dashboard: Customers → [Customer ID] → Payments → Refund
- Always send template CX-REFUND-CONFIRM to customer after processing
- Create Jira ticket under CS-REFUND project with order ID in title

Crypto/non-standard payment refunds:
- Escalate ALL crypto refund requests to Dave Okafor (Finance) + Nadia Petrov (Legal)
- Do NOT process these without written legal clearance

Enterprise SLA on refunds:
- Enterprise customers (>$50k ARR) get priority refund review: 4 business hours SLA
- Regular customers: 2 business day SLA
""", days_ago=67, tags=["refund", "billing", "policy", "alice", "finance"]),

    entry("slack", "Alice Chen", """
#support-ops — IMPORTANT UPDATE

Team — small but critical update to the refund policy. Legal flagged an issue 
with how we were handling EU customers. Effective immediately:

EU customers (identified by billing country in Stripe) requesting refunds within 14 days 
of purchase for DIGITAL PRODUCTS get an automatic full refund under EU consumer law. 
No exceptions, no partial refunds, no approvals needed. Just do it and log the Jira ticket.

This supersedes the 30-day rule for EU customers on digital products only. 
Physical product EU refunds still follow the normal 30-day policy.

Nadia confirmed this is legally required. Don't push back on EU customers on this.
""", days_ago=12, tags=["refund", "eu", "legal", "policy_update"]),

    entry("email", "Marcus Webb", """
To: Alice Chen, Dave Okafor
CC: Jordan Blake
Subject: Refund Authority Limits — UPDATED

Alice, Dave —

Following the board review last week, we're tightening the refund authority limits:

Old limits:
- Support Lead: up to $500 without approval
- Alice Chen: up to $5,000 without approval
- Marcus: up to $50,000

New limits (effective May 1, 2026):
- Support Lead (Preet, Miguel): up to $200 without approval
- Alice Chen: up to $2,000 without approval  
- Dave Okafor: up to $10,000 without approval
- Marcus Webb: up to $50,000
- Above $50,000: requires Marcus + Jordan co-approval

Please update Stripe user permissions accordingly. Elena has the access credentials.
This applies to refunds, credits, and billing adjustments.

Marcus
""", days_ago=6, tags=["refund", "authority", "billing", "limits", "policy_update"]),
]

# ─────────────────────────────────────────────
# PRICING & DISCOUNTS (multi-hop: Sales → Finance → Legal)
# ─────────────────────────────────────────────

PRICING_POLICY = [
    entry("notion", "Priya Nair", """
PRICING TIERS — Product v3.0 (Updated April 2026)
Owner: Priya Nair (VP Product)
Revenue modeling: Marcus Webb (CFO)

Starter Plan: $49/month or $470/year
- Up to 5 users
- 10GB storage
- Standard support (24h SLA)
- No custom integrations

Pro Plan: $149/month or $1,430/year  
- Up to 25 users
- 100GB storage
- Priority support (8h SLA)
- 3 custom integrations
- API access

Enterprise Plan: Custom pricing (base from $2,000/month)
- Unlimited users
- Unlimited storage
- Dedicated support (2h SLA)
- Unlimited integrations
- SLA guarantees with financial penalties
- SOC2 compliance documentation
- Custom contract terms

Discount Authority:
- Up to 10%: Any AE (Account Executive) can apply
- 11–20%: Sales Manager approval (currently Alice Chen acting)
- 21–40%: VP Sales approval [VACANT — route to Dave Okafor + Marcus Webb]
- Above 40%: CFO + CEO approval required
- Startup Program (company <3 years, <15 employees): up to 40% without escalation,
  requires verification via Crunchbase + LinkedIn. Document in Salesforce.
""", days_ago=30, tags=["pricing", "discounts", "authority", "enterprise", "startup"]),

    entry("slack", "Dave Okafor", """
#sales-team

Heads up on the startup program — we've had a few people applying it too broadly.
The startup discount is ONLY for companies that meet ALL three criteria:
1. Founded within the last 3 years (check Crunchbase founding date)
2. Fewer than 15 full-time employees (check LinkedIn)
3. Less than $2M in disclosed funding

If they've raised a Series A ($5M+), they don't qualify regardless of company age.
Run it by me if you're unsure. We've had two cases this quarter where we gave startup
discounts to VC-backed companies that clearly didn't need it. Not happening again.
""", days_ago=18, tags=["pricing", "startup", "discounts", "eligibility"]),

    entry("email", "Nadia Petrov", """
To: Sales Team, Alice Chen, Dave Okafor
Subject: Contract Terms — Do Not Deviate Without Legal Review

Team —

I've noticed several recent contracts going out with non-standard payment terms. 
A reminder of what requires Legal review before sending:

REQUIRES LEGAL REVIEW (send to nadia@company.com, 48h turnaround):
- Net-60 or longer payment terms (standard is Net-30)
- Any liability cap below $500k
- Auto-renewal clauses with less than 60 days notice requirement
- Data processing agreements with EU customers
- Any contract mentioning SOC2 compliance guarantees
- Contracts with government entities (federal, state, or municipal)

DO NOT SEND contracts with the following without explicit CEO sign-off:
- Indemnification clauses that cover consequential damages
- Source code escrow requirements
- Most-favored-nation pricing clauses

Use the standard contract template in Notion under Legal/Templates.
Non-standard terms that go out without review create liability for us.

Nadia
""", days_ago=22, tags=["legal", "contracts", "enterprise", "compliance"]),
]

# ─────────────────────────────────────────────
# ENGINEERING: INCIDENTS, DEPLOYMENTS, RUNBOOKS
# ─────────────────────────────────────────────

ENGINEERING = [
    entry("notion", "Carol Singh", """
INCIDENT RESPONSE RUNBOOK v3.2
Owner: Carol Singh (CTO)
Last updated: April 2026

SEVERITY LEVELS:
- P0 (Outage): >25% of users cannot access core product. Revenue impact.
- P1 (Critical): Core feature broken for significant user segment.
- P2 (High): Important feature degraded, workaround exists.
- P3 (Medium): Minor feature broken, low user impact.
- P4 (Low): Cosmetic issue, no functional impact.

P0/P1 RESPONSE PROTOCOL:
1. On-call engineer pages #incidents Slack channel immediately
2. Page Carol Singh (CTO) via PagerDuty — ID: carol-singh-oncall
3. Incident Commander role assigned (rotating: Sam Torres, Rajan Mehta, David Lee)
4. War room opened: Slack #incident-YYYYMMDD-[brief-description]
5. Status page updated at status.company.com within 15 MINUTES — no exceptions
6. Customer-facing comms: Alice Chen notified to prepare support messaging
7. Executive update to Jordan Blake every 30 minutes until resolved
8. Resolution: post-mortem REQUIRED within 48 hours (template: Notion/Engineering/Postmortems)

P2/P3 RESPONSE:
- Standard Jira ticket under ENG project
- David Lee assigns based on current sprint capacity
- No PagerDuty, no war room required

DATABASE INCIDENTS specifically:
- ALL database issues: page David Lee (DBA responsibilities) first
- Rajan Mehta is backup DBA contact
- Production DB credentials: in 1Password vault "Production-DB" (access: Carol, David, Sam, Rajan)
- NEVER restart production DB without second engineer approval

DEPLOYMENT FREEZE:
- Code freeze 48h before major releases
- No production deploys: Friday 4pm through Monday 9am (except P0 hotfixes)
- Holiday freezes: announced in #engineering 1 week ahead
""", days_ago=45, tags=["incident", "runbook", "oncall", "pagerduty", "deployment"]),

    entry("notion", "Sam Torres", """
AMD MI300X DEPLOYMENT RUNBOOK
Owner: Sam Torres (Platform Lead)
Reviewed by: Rajan Mehta (ML Lead)

VLLM SETUP ON MI300X:

Prerequisites:
- ROCm 6.2+ installed (check: rocm-smi --version)
- Docker with AMD GPU support
- At least 192GB VRAM confirmed (rocm-smi --showmeminfo vram)

Launch command:
  HIP_VISIBLE_DEVICES=0 python -m vllm.entrypoints.openai.api_server \\
    --model meta-llama/Meta-Llama-3-70B-Instruct \\
    --dtype bfloat16 \\
    --max-model-len 8192 \\
    --port 8081 \\
    --tensor-parallel-size 1

COMMON ERRORS:
- OOM on load: reduce --max-model-len to 4096 first, then increase incrementally
- Slow first inference: expected, model is warming up (allow 90s)
- HIP error 712: usually a stale lock file. Run: rm /tmp/hip_*.lock and retry
- Port 8081 in use: check with lsof -i :8081, kill the stale process

PERFORMANCE BENCHMARKS (MI300X, Llama-3 70B, bfloat16):
- Throughput: ~2,400 tokens/sec (batch size 8)
- Latency first token: ~280ms
- Latency per token: ~18ms
- Max concurrent requests sustainable: 12 before degradation

MULTIPLE MODEL SERVING (leveraging 192GB VRAM):
- You can serve Llama-3 70B + BGE-M3 embeddings simultaneously
- BGE-M3 uses ~4GB, leaves ~120GB for 70B model + KV cache
- Command for embedding server (separate port 8082):
  python -m vllm.entrypoints.openai.api_server \\
    --model BAAI/bge-m3 --port 8082 --dtype float16

MONITORING:
- GPU utilization: watch -n 1 rocm-smi
- Temperature limits: throttles at 95°C, shutdown at 105°C
- Alert Sam Torres if sustained >85°C during inference load tests
""", days_ago=20, tags=["amd", "mi300x", "vllm", "rocm", "deployment", "ml"]),

    entry("slack", "Rajan Mehta", """
#ml-platform

Important update on the embedding model situation. We switched from text-embedding-ada-002 
to BAAI/bge-m3 for all internal retrieval last week. Performance comparison:

Ada-002: 68.4% retrieval accuracy on our internal eval set
BGE-M3: 79.1% retrieval accuracy (+10.7 points)

BGE-M3 also supports multilingual out of the box which matters for our EU expansion.
The model runs locally on MI300X so no API costs. Latency is ~8ms per embedding vs
~45ms via OpenAI API. 

Updated the embedding client in core/llm_client.py — if you're still using ada-002
anywhere please switch. The old endpoint is being deprecated June 1.
""", days_ago=8, tags=["ml", "embeddings", "bge", "performance", "migration"]),

    entry("slack", "David Lee", """
#engineering — CRITICAL

We had a near-miss on production yesterday. Someone ran a migration script directly 
on prod DB without going through the standard process. We got lucky that it was 
a read-only operation.

Reminder of the production DB access protocol:
1. ALL schema changes require a migration PR reviewed by at least 2 engineers
2. Run migrations in staging FIRST, confirm with QA sign-off
3. Production migrations: only during maintenance windows (Tuesdays 2-4am UTC)
4. ALWAYS have a rollback script ready before running migration
5. Post in #db-changes channel before and after any production DB operation

This is non-negotiable. Next violation = immediate access revocation.
DB credentials are in 1Password. If you don't have access you shouldn't be touching prod.

—David
""", days_ago=3, tags=["database", "production", "protocol", "security", "engineering"]),

    entry("notion", "Fatima Al-Rashid", """
SECURITY POLICY — ACCESS CONTROL & CREDENTIALS
Owner: Fatima Al-Rashid (Security Lead)
Classification: INTERNAL

PASSWORD & CREDENTIAL MANAGEMENT:
- ALL credentials must be in 1Password (company account)
- No credentials in Slack, email, Notion, or code repositories — ever
- Rotate API keys every 90 days (automated reminder via 1Password)
- Shared credentials require approval from Fatima + relevant team lead

MFA REQUIREMENTS:
- Mandatory on: AWS console, GitHub, 1Password, Salesforce, Stripe, Google Workspace
- Use hardware key (YubiKey) for: AWS root account, GitHub admin, Stripe
- TOTP acceptable for all other services

INCIDENT REPORTING:
- Suspected credential compromise: page Fatima immediately via PagerDuty ID: fatima-security
- Do NOT attempt to investigate/remediate on your own first
- Contain first (revoke/rotate), then investigate

THIRD-PARTY ACCESS:
- Vendors requiring system access: 90-day maximum, reviewed quarterly
- All vendor access logged in Notion under Security/Vendor-Access-Log
- Thornfield Partners (our compliance vendor): has read-only access to audit logs
  Contact: compliance@thornfield.com | Renewal: August 2026

PENETRATION TESTING:
- Scheduled annually (next: Q3 2026, vendor TBD)
- Rajan Mehta runs internal red team exercises quarterly
- Results and remediation tracked in Jira under SEC project
""", days_ago=35, tags=["security", "credentials", "mfa", "access_control", "policy"]),
]

# ─────────────────────────────────────────────
# CUSTOMER SLA & SUPPORT
# ─────────────────────────────────────────────

CUSTOMER_SLA = [
    entry("notion", "Alice Chen", """
CUSTOMER SLA MATRIX — Updated May 2026
Owner: Alice Chen (Head of CS)
Approved by: Jordan Blake (CEO)

RESPONSE TIME SLAs BY PLAN:

Starter Plan:
- P1/P2 issues: First response within 24 business hours
- P3/P4 issues: First response within 3 business days
- Support channel: Email only (support@company.com)
- No uptime SLA guarantee

Pro Plan:
- P1 issues: First response within 4 business hours
- P2 issues: First response within 8 business hours
- P3/P4 issues: First response within 1 business day
- Support channel: Email + in-app chat
- Uptime SLA: 99.5% monthly (excluding scheduled maintenance)
- Credit: 10% monthly fee for each 1% below SLA

Enterprise Plan:
- P1 issues: First response within 1 hour (24/7)
- P2 issues: First response within 2 hours (24/7)
- P3 issues: First response within 4 business hours
- P4 issues: First response within 1 business day
- Support channel: Email + in-app chat + dedicated Slack channel + phone
- Uptime SLA: 99.9% monthly
- Credit: 25% monthly fee per 1% below SLA
- Named CSM (Customer Success Manager) assigned

ESCALATION PATH:
Tier 1 (Preet, Miguel) → Tier 2 (Alice) → Tier 3 (David Lee for technical) → Carol (CTO)

ENTERPRISE ESCALATION (>$50k ARR):
Any enterprise customer threatening churn → immediate flag to Dave Okafor + Alice + Jordan
Response time: Dave/Alice connect with customer within 2 business hours

NOTE: We currently have 3 enterprise customers on named CSM model:
- Apex Logistics (CSM: Preet Kaur)
- Meridian Financial (CSM: Miguel Reyes)  
- TerraCore Industries (CSM: Alice Chen personally)
""", days_ago=14, tags=["sla", "support", "enterprise", "response_time", "escalation"]),

    entry("email", "Jordan Blake", """
To: Alice Chen, Dave Okafor
CC: Carol Singh, Marcus Webb
Subject: TerraCore Industries — URGENT — Escalation

Alice, Dave —

Just got off a call with TerraCore's CTO. They're experiencing P1-level issues with 
our API integration and have been waiting 3 hours without resolution. This is a $280k ARR 
account — our single largest customer.

Their technical contact is Wei Zhang (wei.zhang@terracore.com). Their engineering lead
is going to have a call with Carol and Sam at 3pm today to debug.

Alice — please send an immediate apology from the company level, not just support level.
Dave — I need you to prepare a credit proposal. Given our SLA breach I'd suggest 
a 20% credit on their next invoice. Run it by Marcus first.

This cannot happen again with TerraCore. If we lose them that's a material revenue impact.
I'm adding this to Monday's exec standup agenda.

Jordan
""", days_ago=1, tags=["enterprise", "escalation", "terracore", "sla_breach", "customer"]),

    entry("slack", "Preet Kaur", """
#support-ops

Documenting a recurring issue we keep seeing with Apex Logistics for the runbook:

Apex Logistics frequently hits rate limits on our API because they're running batch 
jobs at 2am UTC (their off-hours ETL pipeline). Their account is on Pro plan but their 
usage pattern is Enterprise-level.

Current workaround Alice approved:
- We've whitelisted their IP range (10.42.0.0/16) for 2x rate limits temporarily
- This is NOT documented in their contract — it's a goodwill gesture
- Expires June 30, 2026 unless renewed
- Contact at Apex: Rajesh Patel (r.patel@apexlogistics.com)

We should either upgrade them to Enterprise or formalize the rate limit increase.
Dave is aware — this came up in the renewal conversation last month.
""", days_ago=9, tags=["customer", "apex_logistics", "rate_limit", "workaround", "sla"]),
]

# ─────────────────────────────────────────────
# HR & ONBOARDING
# ─────────────────────────────────────────────

HR_POLICY = [
    entry("notion", "HR System", """
EMPLOYEE ONBOARDING CHECKLIST — Week 1
Owner: Emma Davis (HR, outsourced to PeopleFirst Partners)
Contact: hr@peoplefirst.com | Internal coord: Jordan Blake's EA (Jamie)

DAY 1:
□ Equipment pickup from IT (Sam Torres handles, submit request 48h in advance via help@company.com)
□ Google Workspace account creation (IT ticket)
□ 1Password onboarding (Fatima Al-Rashid sends invite)
□ Security training module in Workday (mandatory, 2 hours, must complete Day 1)
□ Employee handbook signature (DocuSign, sent by PeopleFirst)
□ Slack workspace invite + add to #general, #random, #team-[department]

WEEK 1:
□ Shadow your manager for 2 days
□ Meet your skip-level (30-min coffee chat, manager schedules)
□ Complete product walkthrough (Priya Nair runs this every Monday 2pm)
□ Set up local dev environment (Engineering only — see Notion/Engineering/Dev-Setup)
□ Complete GDPR/data handling training (Fatima sends link)

EQUIPMENT:
- MacBook Pro 14" (default) or 16" for engineering roles
- YubiKey for MFA (mandatory, Fatima provides)
- Equipment requests >$500 need manager approval in Workday

SYSTEM ACCESS (submit request via IT ticket):
- GitHub (Engineering, Product) — David Lee approves
- AWS console (Engineering) — Sam Torres approves, Fatima audits
- Stripe (Finance, CS leads only) — Marcus Webb approves
- Salesforce (Sales, CS) — Alice Chen approves for CS, Dave for Finance
- Production systems: additional security review, Fatima sign-off required
""", days_ago=60, tags=["onboarding", "hr", "new_hire", "access", "equipment"]),

    entry("slack", "Carol Singh", """
#engineering

For the new engineers joining next month (we have 3 starting June 2 — Yuki Tanaka,
Bruno Ferreira, and one more TBD from the current interview loop):

Please make sure you've documented your systems before they join. We have a habit of 
onboarding people and then expecting them to just figure things out. 

Specifically I need:
1. Sam — update the platform setup guide in Notion (it's 8 months out of date)
2. Rajan — document the ML pipeline end to end, not just the model serving part
3. David — write up the DB schema overview doc we keep promising

These need to be done by May 28. I'm blocking time on everyone's calendar.

The new hires will be doing a proper 90-day structured onboarding. David Lee is 
their engineering buddy. Priya will run them through the product side.
""", days_ago=4, tags=["onboarding", "engineering", "documentation", "hiring"]),
]

# ─────────────────────────────────────────────
# PRODUCT & ROADMAP (creates cross-domain refs)
# ─────────────────────────────────────────────

PRODUCT = [
    entry("notion", "Priya Nair", """
PRODUCT ROADMAP — Q2/Q3 2026
Owner: Priya Nair (VP Product)
Last reviewed: Jordan Blake, Carol Singh, Marcus Webb

Q2 2026 (April–June) — IN PROGRESS:
✅ Multi-modal input (image + text) — Rajan leading, targeting May 31
🔄 EU data residency (GDPR compliance) — Nadia + Sam, targeting June 15
⏳ Enterprise SSO (SAML/OIDC) — David Lee, targeting June 30
⏳ API v3 (GraphQL) — Kai Okonkwo leading, replaces REST v2 by Q4

Q3 2026 (July–September):
- Offline mode for Pro+ plans
- Advanced analytics dashboard
- Salesforce native integration (HIGH PRIORITY — multiple enterprise requests)
- Mobile app v2.0 (iOS + Android)

PRICING IMPACT (from Marcus, May 2026):
- EU data residency → adds $200/month to Enterprise plans starting July 1
- Enterprise SSO → included in Enterprise, add-on for Pro ($49/month)
- API v3 → no pricing change, v2 deprecated December 2026

DEPENDENCIES TO FLAG:
- Salesforce integration blocked on legal review of data sharing terms (Nadia)
- Mobile v2.0 blocked on hiring — need 2 mobile engineers (Jamie is recruiting)
- API v3 timeline may slip — Kai is also on EU data residency work
""", days_ago=7, tags=["product", "roadmap", "enterprise", "q2", "q3", "pricing"]),

    entry("email", "Kai Okonkwo", """
To: David Lee, Priya Nair, Sam Torres
Subject: API v2 → v3 Migration — Breaking Changes

Team —

Quick heads up on the breaking changes in API v3 that we need to document before 
we communicate to customers:

BREAKING CHANGES (v2 → v3):
1. Auth: Bearer tokens replace API keys. Old API keys work until Dec 31, 2026.
   New token endpoint: POST /v3/auth/token
   
2. Pricing endpoint moved: /v2/pricing → /v3/catalog/pricing
   (this was already partially moved per Bob's email last month — /v1/prices is dead)
   
3. Pagination: cursor-based replaces offset-based. Response format change:
   Old: { "data": [], "total": 100, "offset": 0 }
   New: { "data": [], "next_cursor": "abc123", "has_more": true }
   
4. Webhooks: new signature format using HMAC-SHA256
   Old webhooks continue working until June 30, 2026 then REQUIRE migration

CUSTOMERS AFFECTED: All 847 API customers. Enterprise customers need direct outreach.
Alice — can your team flag which enterprise accounts are heavy API users?
David — need migration guide written before we send the customer email (targeting May 15).

Kai
""", days_ago=5, tags=["api", "migration", "breaking_changes", "v3", "customers", "engineering"]),
]

# ─────────────────────────────────────────────
# FINANCE & PROCUREMENT
# ─────────────────────────────────────────────

FINANCE = [
    entry("notion", "Marcus Webb", """
PROCUREMENT POLICY — Updated Q1 2026
Owner: Marcus Webb (CFO)

SOFTWARE/SAAS PROCUREMENT:
- <$500/year: Team lead can approve, log in Notion/Finance/Software-Registry
- $500–$5,000/year: Department head approval, Marcus notified
- $5,000–$25,000/year: Marcus Webb approval + Jordan Blake awareness
- >$25,000/year: Board notification required (quarterly review)

HARDWARE PROCUREMENT:
- Standard equipment: IT handles via pre-approved vendor list (Dell, Apple)
- Non-standard (e.g., AMD MI300X GPUs, custom servers): Sam Torres specifies, 
  Marcus approves, minimum 3 vendor quotes required
- AMD MI300X current cost via AMD Developer Cloud: $8.50/hr on-demand
  Reserved 1-year: $4.20/hr (requires Marcus sign-off on commitment)

VENDOR APPROVAL PROCESS:
1. Submit vendor request in Notion/Finance/Vendor-Requests
2. Security review: Fatima Al-Rashid (for any vendor with data access)
3. Legal review: Nadia Petrov (for contracts >$10k or data processing)
4. Finance approval: Marcus Webb
5. PO issued by Elena Vasquez

EXPENSE REPORTING:
- All expenses via Expensify (company account)
- Submit within 30 days of expense
- Receipts required for anything >$25
- International expenses: flag currency + exchange rate used
- Team meals: up to $50/person, manager approval
- Conference/travel: submit Travel Request in Workday minimum 2 weeks ahead

CURRENT BUDGET ALERTS (May 2026):
- ML infrastructure (AMD cloud): 78% of Q2 budget used (watch closely — Rajan alerted)
- Marketing: underspent (42% of Q2 budget, Priya to advise reallocation)
""", days_ago=55, tags=["finance", "procurement", "budget", "vendor", "hardware"]),

    entry("slack", "Rajan Mehta", """
#ml-platform

Heads up to Marcus and Sam — we're burning through the AMD cloud credits faster
than expected. The BrainOS prototype has been running 24/7 on the MI300X instance 
for load testing and we didn't account for that in the Q2 budget.

Current burn: ~$340/day on the MI300X instance (8.50/hr * 40hr/day avg... yes the
instance was left running overnight a few times, my bad).

Options I see:
1. Switch to reserved pricing ($4.20/hr) if we're committed to running this through Q3
2. Use spot instances for non-critical testing (risk of interruption)
3. Add GPU scheduling — only run the full 70B model during business hours,
   use a smaller 8B model overnight for background jobs

I'm going with option 3 starting tomorrow unless someone objects.
Tagging Sam to update the deployment scripts.

Marcus — expect an overage of ~$2,800 vs Q2 ML budget. Sorry, will be more careful.
""", days_ago=2, tags=["finance", "budget", "amd", "ml", "cloud_costs"]),
]

# ─────────────────────────────────────────────
# KNOWLEDGE GAPS (these intentionally trigger low-confidence in the execution agent)
# ─────────────────────────────────────────────

GAPS_AND_CONFLICTS = [
    entry("slack", "Miguel Reyes", """
#support-ops

Does anyone know what the escalation path is for Meridian Financial specifically?
They're a bank so they have specific compliance requirements we agreed to in the contract
but I don't have the contract details. They have SOC2 Type II requirements that affect
how we handle their support tickets (data can't leave certain regions).

Alice mentioned there was a special data handling addendum but I can't find it in Notion.
""", days_ago=1, tags=["escalation", "meridian", "compliance", "gap"], confidence=0.4),

    entry("slack", "Bruno Ferreira", """
#engineering

Wait — what's the current state of the Pricing API? I see references to:
- /v1/prices (mentioned in old docs as deprecated)
- /v2/pricing (Bob's email said this was new as of last Tuesday)
- /v3/catalog/pricing (Kai's email about v3 migration)

Which one should I be pointing the frontend to right now? The docs in Notion haven't 
been updated. Can someone clarify?
""", days_ago=1, tags=["api", "pricing", "confusion", "gap"], confidence=0.3),

    entry("slack", "Sam Torres", """
#general

Genuine question — who do we contact for the AMD Developer Cloud billing issues?
We had a credit discrepancy last month that Marcus flagged but I'm not sure if it goes
through our usual AWS support process or AMD has a separate account manager.

Also does anyone know if our AMD Developer Cloud account is linked to the AMD AI 
Developer Program membership? Rajan mentioned we need to be enrolled to get hackathon
credits but I can't find the confirmation email.
""", days_ago=3, tags=["amd", "billing", "vendor", "gap"], confidence=0.4),
]

# ─────────────────────────────────────────────
# DEPRECATED / SUPERSEDED KNOWLEDGE (tests the brain's recency awareness)
# ─────────────────────────────────────────────

DEPRECATED = [
    entry("notion", "Old System", """
[DEPRECATED - DO NOT USE]
REFUND POLICY v1.0 — Pre-March 2026

All refund requests processed manually. Support lead submits request to finance@company.com.
Finance team reviews within 5 business days. No automatic approvals.
Refunds over $1,000 require VP Sales (Sarah Chen) signature.
""", days_ago=100, tags=["refund", "deprecated", "old_policy"], confidence=0.1),

    entry("slack", "Bob Chen", """
#dev-team (old message, context: pre-migration)

The Pricing API is at /v1/prices. Use this endpoint for all pricing queries.
Make sure to include the API key in the X-API-Key header.
""", days_ago=45, tags=["api", "pricing", "deprecated"], confidence=0.1),
]

# ─────────────────────────────────────────────
# ASSEMBLE EVERYTHING
# ─────────────────────────────────────────────

ALL_DATA = (
    ORG_CHART +
    REFUND_POLICY +
    PRICING_POLICY +
    ENGINEERING +
    CUSTOMER_SLA +
    HR_POLICY +
    PRODUCT +
    FINANCE +
    GAPS_AND_CONFLICTS +
    DEPRECATED
)

# Shuffle slightly to simulate real-world ingestion order
mid = len(ALL_DATA) // 2
ALL_DATA = ALL_DATA[1:mid] + ALL_DATA[:1] + ALL_DATA[mid:]

# ─────────────────────────────────────────────
# KNOWLEDGE GRAPH RELATIONS
# (explicit entity links for NetworkX — supplements the vector store)
# ─────────────────────────────────────────────

KNOWLEDGE_GRAPH = {
    "entities": [
        # People
        {"id": "jordan_blake",   "type": "person",  "role": "CEO",              "email": "jordan@company.com"},
        {"id": "carol_singh",    "type": "person",  "role": "CTO",              "email": "carol@company.com"},
        {"id": "marcus_webb",    "type": "person",  "role": "CFO",              "email": "marcus@company.com"},
        {"id": "alice_chen",     "type": "person",  "role": "Head of CS",       "email": "alice@company.com"},
        {"id": "dave_okafor",    "type": "person",  "role": "Finance Lead + Acting Enterprise Sales", "email": "dave@company.com"},
        {"id": "priya_nair",     "type": "person",  "role": "VP Product",       "email": "priya@company.com"},
        {"id": "david_lee",      "type": "person",  "role": "Engineering Manager", "email": "david@company.com"},
        {"id": "sam_torres",     "type": "person",  "role": "Platform Lead",    "email": "sam@company.com"},
        {"id": "rajan_mehta",    "type": "person",  "role": "ML Lead",          "email": "rajan@company.com"},
        {"id": "fatima_alrashid","type": "person",  "role": "Security Lead",    "email": "fatima@company.com"},
        {"id": "nadia_petrov",   "type": "person",  "role": "General Counsel",  "email": "nadia@company.com"},
        {"id": "preet_kaur",     "type": "person",  "role": "Support Lead",     "email": "preet@company.com"},
        {"id": "miguel_reyes",   "type": "person",  "role": "Support Lead",     "email": "miguel@company.com"},
        {"id": "kai_okonkwo",    "type": "person",  "role": "Senior Engineer",  "email": "kai@company.com"},
        {"id": "elena_vasquez",  "type": "person",  "role": "AP/AR",            "email": "elena@company.com"},
        # Customers
        {"id": "terracore",      "type": "customer", "arr": 280000, "plan": "enterprise", "csm": "alice_chen"},
        {"id": "apex_logistics", "type": "customer", "arr": 85000,  "plan": "enterprise", "csm": "preet_kaur"},
        {"id": "meridian_fin",   "type": "customer", "arr": 120000, "plan": "enterprise", "csm": "miguel_reyes"},
        # Systems
        {"id": "stripe",         "type": "system",  "purpose": "payments/refunds"},
        {"id": "jira",           "type": "system",  "purpose": "ticketing"},
        {"id": "salesforce",     "type": "system",  "purpose": "crm"},
        {"id": "pagerduty",      "type": "system",  "purpose": "oncall_alerting"},
        {"id": "onepw",          "type": "system",  "purpose": "credential_management"},
        {"id": "amd_cloud",      "type": "system",  "purpose": "ml_compute"},
        # Policies
        {"id": "refund_policy",      "type": "policy", "version": "2.1", "owner": "alice_chen"},
        {"id": "pricing_policy",     "type": "policy", "version": "3.0", "owner": "priya_nair"},
        {"id": "incident_runbook",   "type": "policy", "version": "3.2", "owner": "carol_singh"},
        {"id": "security_policy",    "type": "policy", "version": "1.0", "owner": "fatima_alrashid"},
        {"id": "procurement_policy", "type": "policy", "version": "1.0", "owner": "marcus_webb"},
    ],

    "relations": [
        # Reporting structure
        {"from": "carol_singh",    "to": "jordan_blake",  "rel": "reports_to"},
        {"from": "marcus_webb",    "to": "jordan_blake",  "rel": "reports_to"},
        {"from": "priya_nair",     "to": "jordan_blake",  "rel": "reports_to"},
        {"from": "alice_chen",     "to": "jordan_blake",  "rel": "reports_to_temporarily"},
        {"from": "david_lee",      "to": "carol_singh",   "rel": "reports_to"},
        {"from": "sam_torres",     "to": "carol_singh",   "rel": "reports_to"},
        {"from": "rajan_mehta",    "to": "carol_singh",   "rel": "reports_to"},
        {"from": "fatima_alrashid","to": "carol_singh",   "rel": "reports_to"},
        {"from": "dave_okafor",    "to": "marcus_webb",   "rel": "reports_to"},
        {"from": "elena_vasquez",  "to": "marcus_webb",   "rel": "reports_to"},
        {"from": "nadia_petrov",   "to": "jordan_blake",  "rel": "reports_to"},
        {"from": "preet_kaur",     "to": "alice_chen",    "rel": "reports_to"},
        {"from": "miguel_reyes",   "to": "alice_chen",    "rel": "reports_to"},
        # Ownership
        {"from": "alice_chen",     "to": "refund_policy",      "rel": "owns"},
        {"from": "priya_nair",     "to": "pricing_policy",     "rel": "owns"},
        {"from": "carol_singh",    "to": "incident_runbook",   "rel": "owns"},
        {"from": "fatima_alrashid","to": "security_policy",    "rel": "owns"},
        {"from": "marcus_webb",    "to": "procurement_policy", "rel": "owns"},
        # Approval chains
        {"from": "refund_policy",   "to": "marcus_webb",  "rel": "approved_by"},
        {"from": "pricing_policy",  "to": "marcus_webb",  "rel": "revenue_modeled_by"},
        {"from": "pricing_policy",  "to": "jordan_blake", "rel": "approved_by"},
        # Customer → CSM
        {"from": "terracore",      "to": "alice_chen",    "rel": "csm_assigned"},
        {"from": "apex_logistics", "to": "preet_kaur",    "rel": "csm_assigned"},
        {"from": "meridian_fin",   "to": "miguel_reyes",  "rel": "csm_assigned"},
        # Customer escalation paths
        {"from": "terracore",      "to": "dave_okafor",   "rel": "finance_escalation"},
        {"from": "terracore",      "to": "jordan_blake",  "rel": "exec_escalation"},
        {"from": "apex_logistics", "to": "dave_okafor",   "rel": "renewal_owner"},
        # System permissions
        {"from": "alice_chen",     "to": "stripe",        "rel": "has_access"},
        {"from": "dave_okafor",    "to": "stripe",        "rel": "has_access"},
        {"from": "elena_vasquez",  "to": "stripe",        "rel": "has_access"},
        {"from": "fatima_alrashid","to": "onepw",         "rel": "admin"},
        {"from": "sam_torres",     "to": "amd_cloud",     "rel": "manages"},
        {"from": "rajan_mehta",    "to": "amd_cloud",     "rel": "has_access"},
        # Cross-domain dependencies (multi-hop)
        {"from": "refund_policy",      "to": "stripe",       "rel": "executed_via"},
        {"from": "refund_policy",      "to": "jira",         "rel": "logged_in"},
        {"from": "incident_runbook",   "to": "pagerduty",    "rel": "alerts_via"},
        {"from": "incident_runbook",   "to": "alice_chen",   "rel": "notifies_for_comms"},
        {"from": "pricing_policy",     "to": "salesforce",   "rel": "logged_in"},
        {"from": "security_policy",    "to": "onepw",        "rel": "enforced_via"},
        {"from": "procurement_policy", "to": "nadia_petrov", "rel": "legal_review_by"},
        {"from": "procurement_policy", "to": "fatima_alrashid", "rel": "security_review_by"},
        # Temporal supersessions
        {"from": "refund_policy",  "to": "deprecated_refund_v1", "rel": "supersedes"},
    ],

    "conflicts": [
        {
            "id": "api_endpoint_conflict",
            "description": "Pricing API endpoint referenced in 3 conflicting places: /v1/prices (deprecated), /v2/pricing (Bob's email), /v3/catalog/pricing (Kai's migration doc). Current canonical: /v2/pricing, with /v3 coming in Q3.",
            "entities_involved": ["kai_okonkwo", "pricing_policy"],
            "resolution": "Use /v2/pricing now. /v3 migration guide pending from David Lee.",
            "severity": "medium"
        },
        {
            "id": "vp_sales_vacancy",
            "description": "VP Sales role vacant since Sarah Chen departure. Enterprise account ownership split between Alice (<$50k ARR) and Dave (>$50k ARR). Contract signing requires Dave + Jordan co-sign for all enterprise deals.",
            "entities_involved": ["alice_chen", "dave_okafor", "jordan_blake"],
            "resolution": "New VP Sales expected June 15. Until then follow org chart pinned message.",
            "severity": "high"
        },
        {
            "id": "eu_refund_override",
            "description": "Standard 30-day refund policy conflicts with EU consumer law 14-day digital product rule. EU customers get automatic refund within 14 days — this overrides the standard policy.",
            "entities_involved": ["refund_policy", "nadia_petrov"],
            "resolution": "EU digital product: 14-day automatic. Non-EU / physical: standard 30-day policy.",
            "severity": "high"
        },
        {
            "id": "meridian_compliance_gap",
            "description": "Meridian Financial has SOC2 + data residency requirements in their contract addendum that is not documented in Notion. Support team unaware of special handling requirements.",
            "entities_involved": ["meridian_fin", "miguel_reyes", "nadia_petrov"],
            "resolution": "UNRESOLVED — addendum must be located and documented.",
            "severity": "critical"
        }
    ]
}

# ─────────────────────────────────────────────
# DEMO TASKS (printed for human to test against /execute)
# ─────────────────────────────────────────────

DEMO_TASKS = [
    # High confidence — should execute cleanly
    "A customer was charged twice for order #8821. They're on the Pro plan. Handle it.",
    "TerraCore Industries is threatening to churn. What's the escalation protocol?",
    "A P1 incident just hit — the API is returning 500s for 30% of users. What do I do?",
    "Sales wants to give a 45% discount to a 2-year-old startup with 8 employees. Is this allowed?",
    "A new engineer starts Monday. What does their Day 1 look like?",
    "The MI300X instance is throwing HIP error 712. How do I fix it?",
    # Medium confidence — should retrieve but may flag gaps
    "An EU customer wants a refund 10 days after buying a digital subscription.",
    "Who approves a $15,000 software procurement request?",
    "Apex Logistics is hitting rate limits again at 2am UTC. What's the current workaround?",
    # Low confidence — should trigger gap detection
    "What are Meridian Financial's special compliance requirements for support tickets?",
    "Which pricing API endpoint should I use right now — v1, v2, or v3?",
    "Is our AMD Developer Cloud account enrolled in the AMD AI Developer Program?",
]


def generate():
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    os.makedirs(out_dir, exist_ok=True)

    # Write raw sources
    sources_path = os.path.join(out_dir, "mock_sources.json")
    with open(sources_path, "w") as f:
        json.dump(ALL_DATA, f, indent=2)

    # Write knowledge graph
    graph_path = os.path.join(out_dir, "knowledge_graph.json")
    with open(graph_path, "w") as f:
        json.dump(KNOWLEDGE_GRAPH, f, indent=2)

    # Write demo tasks
    tasks_path = os.path.join(out_dir, "demo_tasks.json")
    with open(tasks_path, "w") as f:
        json.dump({"tasks": DEMO_TASKS}, f, indent=2)

    print("=" * 60)
    print("BrainOS Seed Data Generator")
    print("=" * 60)
    print(f"\n✓ {len(ALL_DATA)} knowledge chunks → {sources_path}")
    print(f"✓ {len(KNOWLEDGE_GRAPH['entities'])} entities, "
          f"{len(KNOWLEDGE_GRAPH['relations'])} relations, "
          f"{len(KNOWLEDGE_GRAPH['conflicts'])} conflicts → {graph_path}")
    print(f"✓ {len(DEMO_TASKS)} demo tasks → {tasks_path}")

    print("\nKnowledge breakdown:")
    source_counts = {}
    topic_counts  = {}
    for item in ALL_DATA:
        source_counts[item["source_type"]] = source_counts.get(item["source_type"], 0) + 1
        for tag in item.get("tags", []):
            topic_counts[tag] = topic_counts.get(tag, 0) + 1

    for src, count in sorted(source_counts.items()):
        print(f"  {src:10s}: {count} chunks")

    print("\nTop tags:")
    for tag, count in sorted(topic_counts.items(), key=lambda x: -x[1])[:15]:
        print(f"  {tag:25s}: {count}")

    print("\nConflicts seeded (will trigger gap detection):")
    for c in KNOWLEDGE_GRAPH["conflicts"]:
        sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(c["severity"], "⚪")
        print(f"  {sev_icon} [{c['severity'].upper():8s}] {c['id']}")

    print("\nDemo tasks to test against /execute:")
    for i, task in enumerate(DEMO_TASKS, 1):
        print(f"  {i:2d}. {task}")

    print("\n✓ Ready. Run: python scripts/seed_demo_data.py to ingest into BrainStore.")


if __name__ == "__main__":
    generate()