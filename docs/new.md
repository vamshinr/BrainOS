Here is a clean doc you can copy.

```md
# BrainOS Docs + Slack Realtime Decision Alerts

## What This Feature Does

BrainOS now supports a customer onboarding flow for:

1. Ingesting customer docs into BrainOS.
2. Connecting Slack realtime message events.
3. Routing Slack messages into BrainOS ingestion.
4. Extracting only high-confidence `decision` knowledge units.
5. Showing CEO-relevant key decisions as internal BrainOS popup alerts.

This feature does **not** post messages back into Slack. Slack is the input source. BrainOS is where the CEO decision alert appears.

---

## How The Flow Works

1. A Slack message event is sent to:

```text
POST /api/slack/events
```

2. The Next.js route proxies the event to the Python FastAPI backend.

3. The backend verifies the Slack signature using `SLACK_SIGNING_SECRET`.

4. If the event channel is listed in:

```bash
SLACK_REALTIME_INGEST_CHANNELS
```

BrainOS queues a realtime Slack ingestion job.

5. If the same channel is also listed in:

```bash
SLACK_CEO_DECISION_ALERT_CHANNELS
```

BrainOS checks extracted units after ingestion.

6. If a new extracted unit is:

```text
kind = decision
confidence >= CEO_DECISION_ALERT_MIN_CONFIDENCE
```

BrainOS creates a CEO decision alert.

7. The frontend listens to:

```text
GET /api/decision-alerts/stream
```

and shows a popup without refreshing the page.

8. A user can acknowledge or dismiss the alert. Acknowledged alerts disappear and stay gone after reload.

---

## Required Environment Variables

In:

```text
/Users/rajveerrathod/Work/AMD_hackathon/BrainOS/src/python_backend/.env
```

make sure these exist:

```bash
SLACK_MCP_ACCESS_TOKEN=...
SLACK_SIGNING_SECRET=...
SLACK_REALTIME_INGEST_CHANNELS=C_TEST
SLACK_CEO_DECISION_ALERT_CHANNELS=C_TEST
SLACK_ALLOWED_CHANNELS=C_TEST
SLACK_DEFAULT_DEPARTMENT=engineering
```

Optional confidence threshold:

```bash
CEO_DECISION_ALERT_MIN_CONFIDENCE=0.78
```

Default is `0.78`.

---

## Start The Backend

From repo root:

```bash
cd /Users/rajveerrathod/Work/AMD_hackathon/BrainOS

set -a
source src/python_backend/.env
set +a

cd src/python_backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8081 --reload
```

Backend runs on:

```text
http://localhost:8081
```

---

## Start The Frontend

In another terminal:

```bash
cd /Users/rajveerrathod/Work/AMD_hackathon/BrainOS
npm run dev
```

Frontend runs on:

```text
http://localhost:3000
```

Useful pages:

```text
http://localhost:3000/onboarding
http://localhost:3000/slack
http://localhost:3000
```

---

## Verify Slack Realtime Config

Run:

```bash
curl http://localhost:3000/api/slack/health
```

Expected fields:

```json
{
  "realtime_ingest_channels": ["C_TEST"],
  "ceo_decision_alert_channels": ["C_TEST"],
  "realtime_ingest_enabled": true,
  "ceo_decision_alerts_enabled": true
}
```

Also check `/slack`. The page should show the “Realtime Decision Alerts” section.

---

## Send A Signed Local Slack Event

Because `SLACK_SIGNING_SECRET` is configured, local test events must be signed.

Run this as one block:

```bash
cd /Users/rajveerrathod/Work/AMD_hackathon/BrainOS

set -a
source src/python_backend/.env
set +a

BODY='{"type":"event_callback","event":{"type":"message","channel":"C_TEST","user":"U_CEO","ts":"1710000000.000000","text":"Decision: we are standardizing on Stripe for enterprise billing starting next quarter."}}'

TS=$(date +%s)

SIG=$(python3 -c 'import hmac, hashlib, os, sys
ts, body = sys.argv[1:3]
secret = os.environ["SLACK_SIGNING_SECRET"]
print("v0=" + hmac.new(secret.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256).hexdigest())' "$TS" "$BODY")

echo "TS=$TS"
echo "SIG=$SIG"

curl -X POST http://localhost:3000/api/slack/events \
  -H "Content-Type: application/json" \
  -H "X-Slack-Request-Timestamp: $TS" \
  -H "X-Slack-Signature: $SIG" \
  -d "$BODY"
```

Expected response:

```json
{
  "ok": true,
  "queued_realtime_ingest": {
    "queued": true,
    "job_id": "93096a55",
    "status": "queued",
    "queue_position": 1,
    "title": "Slack Realtime: C_TEST / 1710000000.000000"
  }
}
```

---

## Check The Job

Replace the job id with your returned `job_id`:

```bash
curl http://localhost:3000/api/jobs/93096a55
```

Expected successful job:

```json
{
  "id": "93096a55",
  "kind": "slack_realtime",
  "status": "completed",
  "result": {
    "units_extracted": 1,
    "units_stored": 1,
    "alerts_created": 1,
    "alert_ids": ["71d8dbb6-1"]
  }
}
```

---

## Check Decision Alerts

```bash
curl http://localhost:3000/api/decision-alerts
```

Expected response:

```json
{
  "alerts": [
    {
      "id": "71d8dbb6-1",
      "statement": "The company is standardizing on Stripe for enterprise billing starting next quarter.",
      "subject": "enterprise billing",
      "confidence": 1,
      "channelId": "C_TEST",
      "threadTs": "1710000000.000000",
      "status": "open"
    }
  ],
  "min_confidence": 0.78
}
```

The popup should also appear in the BrainOS UI:

```text
http://localhost:3000
```

---

## Acknowledge The Alert

Replace the alert id with your returned alert id:

```bash
curl -X POST http://localhost:3000/api/decision-alerts/71d8dbb6-1/ack
```

Expected response:

```json
{
  "ok": true,
  "alert": {
    "id": "71d8dbb6-1",
    "status": "acknowledged"
  }
}
```

Then check open alerts again:

```bash
curl http://localhost:3000/api/decision-alerts
```

Expected:

```json
{
  "alerts": [],
  "min_confidence": 0.78
}
```

The popup should disappear and stay gone after reload.

---

## Dismiss Instead Of Acknowledge

```bash
curl -X POST http://localhost:3000/api/decision-alerts/<alert_id>/dismiss
```

Dismissed alerts also disappear from the open alert list.

---

## What You Should See In Slack

Nothing is posted back into Slack for this feature.

This path is intentionally:

```text
Slack message -> BrainOS ingest -> CEO decision popup
```

It does not reply in Slack and does not spam the channel.

Slack replies only happen through the existing ask/post features, such as:

```text
/brainos ask <question>
/brainos post <question>
```

or configured app mention / auto-answer flows.

---

## Troubleshooting

### Error: Missing Slack signature headers

You called `/api/slack/events` without signing the request.

Fix: use the signed curl block above.

---

### Error: Stale Slack request timestamp

Your `$TS` is too old.

Fix: regenerate `TS` and `SIG` immediately before curl:

```bash
TS=$(date +%s)
```

Slack allows only about 5 minutes of clock skew.

---

### Event Accepted But No Alert Created

Check the job:

```bash
curl http://localhost:3000/api/jobs/<job_id>
```

Common causes:

1. Job failed because the LLM backend is not configured.
2. The message was not extracted as `kind: decision`.
3. Confidence was below `CEO_DECISION_ALERT_MIN_CONFIDENCE`.
4. `SLACK_CEO_DECISION_ALERT_CHANNELS` does not include the channel.
5. Backend was not restarted after changing `.env`.

---

## Successful Test Evidence

Example accepted event:

```json
{
  "ok": true,
  "queued_realtime_ingest": {
    "queued": true,
    "job_id": "93096a55",
    "status": "queued",
    "queue_position": 1,
    "title": "Slack Realtime: C_TEST / 1710000000.000000"
  }
}
```

Example alert:

```json
{
  "id": "71d8dbb6-1",
  "unitId": "991d7e08-5",
  "statement": "The company is standardizing on Stripe for enterprise billing starting next quarter.",
  "subject": "enterprise billing",
  "confidence": 1,
  "sourceId": "926153cd",
  "sourceTitle": "Slack Realtime: C_TEST / 1710000000.000000",
  "channelId": "C_TEST",
  "channelName": "C_TEST",
  "threadTs": "1710000000.000000",
  "evidenceQuote": "we are standardizing on Stripe for enterprise billing starting next quarter.",
  "status": "open"
}
```

Example completed job:

```json
{
  "id": "93096a55",
  "kind": "slack_realtime",
  "status": "completed",
  "result": {
    "units_extracted": 1,
    "units_stored": 1,
    "alerts_created": 1,
    "alert_ids": ["71d8dbb6-1"]
  }
}
```

Example after acknowledge:

```json
{
  "alerts": [],
  "min_confidence": 0.78
}
```
```