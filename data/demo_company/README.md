# Helix Outdoor — BrainOS demo company

A 78-person Series-B D2C outdoor gear brand. Designed to exercise every BrainOS differentiator in one cohesive narrative.

## Why this persona

| Differentiator | Where it shows up in this dataset |
|---|---|
| **Directed graph** | Customer → CSM → escalation chain (Camp Cosmos → Cara → Diego) ; factory → owner ; webhook → service ; org reporting lines |
| **Supersession** | Refund authority $2,000 → $1,000 (May 1) ; MSA lead time 21d → 28d (Tet 2026) ; EU 14-day digital overrides 7-day blanket |
| **Conflict surfacing** | Trail Club 60-day vs Returns Policy 30-day ; legacy `/v1/inventory` vs `/v2/shipbob/inventory` |
| **Multimodal extraction** | Architecture diagram (signature-verification gotcha annotated) ; QC whiteboard photo ; org-chart screenshot |
| **Gotcha capture** | Slack-only knowledge: Lot 24-A-118 zipper defect ; ShipBob nightly maintenance signature drop |
| **Knowledge gaps** | VP Ops vacant, supplier-onboarding paused ; AMD Developer Cloud has no documented owner ; Bandung Crafted has no signed MSA |
| **Agent skills** | All of the above compile into actionable Agent Rules in SKILLS.md |

## File layout

```
data/demo_company/
├── README.md                  ← you are here
├── build.py                   ← regenerates the PDFs / DOCX / PNGs
├── QUERIES.md                 ← 14 demo /ask queries + capability mapping
├── DEMO_SCRIPT.md             ← 90-second on-camera script with backup paths
├── FEEDBACK.md                ← what to learn, how to collect, what NOT to ask
│
├── text/                      ← 10 paste-into-/ingest text files
│   ├── 01_slack_org_chart_pinned.txt          (org chart + interim coverage)
│   ├── 02_slack_maya_departure.txt            (VP Ops departure / supplier coverage)
│   ├── 03_slack_lot_24A118_defect.txt         (defective lot - the headline gotcha)
│   ├── 04_email_camp_cosmos_escalation.txt    (top wholesale account at risk)
│   ├── 05_slack_webhook_gotcha.txt            (ShipBob signature bug + 2-eng rule)
│   ├── 06_email_eu_returns_law.txt            (legal supersession of 7-day rule)
│   ├── 07_slack_factory_delay_tet.txt         (lead-time supersession)
│   ├── 08_email_refund_authority_update.txt   (refund-limits supersession)
│   ├── 09_slack_vip_returns.txt               (Trail Club 60-day window)
│   └── 10_slack_amd_billing_gap.txt           (gap: AMD vendor owner unknown)
│
├── pdf/                       ← 3 generated PDFs
│   ├── returns_policy_v2_1.pdf
│   ├── saigon_texco_msa.pdf
│   └── q2_vendor_risk_report.pdf
│
├── docx/                      ← 2 generated DOCX
│   ├── security_access_policy.docx
│   └── sla_matrix.docx
│
└── images/                    ← 3 generated PNGs (for VLM ingest)
    ├── architecture.png
    ├── qc_whiteboard.png
    └── org_chart.png
```

## Quickstart

1. Regenerate the binary files (only needed once or after editing `build.py`):
   ```bash
   ./src/python_backend/venv/bin/python data/demo_company/build.py
   ```
2. Start the backend + frontend (`main.py`, `npm run dev`).
3. Visit `/ingest`, drag-drop everything in `text/` into the **Text** tab, everything in `pdf/` and `docx/` into the **File** tab, everything in `images/` into the **Image** tab.
4. Visit `/` — should now show ~10 sources, ~50 entities, 100+ units.
5. Run the queries in `QUERIES.md` against `/ask`.
6. Read `DEMO_SCRIPT.md` and rehearse twice before going live.
7. Hand judges a copy of `FEEDBACK.md` section 2.2 after the demo.

## Notes for the operator

- **Ingest order matters for the supersession demo.** To force the brain to actually `supersede` rather than emit two independent units, you should ingest the *older* fact first (the v2.1 PDF, `08_email` PRE-rule etc.). The seed `text/` files are numbered roughly chronologically — file 06 is older than file 09 etc. — so ingesting them in numbered order produces the cleanest reconciliation timeline.
- **The brain works without images.** If your VLM endpoint is flaky, demo without the `images/` folder — the text + PDF + DOCX content alone is enough to demonstrate Tiers 1-7 of QUERIES.md except Q10 and Q11.
- **Contracts:** all entities are fictional. "Saigon TexCo," "Camp Cosmos," "Bandung Crafted" do not exist. The lot-defect scenario is illustrative; real-world QC processes are more involved.
