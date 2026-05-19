"""BrainOS backend entry point — thin orchestration layer only."""
from __future__ import annotations
import os
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import asyncio
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="BrainOS Multi-Agent Backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
from routes.health      import router as health_router
from routes.ingest      import router as ingest_router
from routes.ask         import router as ask_router
from routes.state       import router as state_router
from routes.jobs        import router as jobs_router
from routes.skills      import router as skills_router
from routes.conflicts   import router as conflicts_router
from routes.onboard     import router as onboard_router
from routes.onboarding  import router as onboarding_router
from routes.alerts      import router as alerts_router
from routes.slack       import router as slack_router

app.include_router(health_router)
app.include_router(ingest_router)
app.include_router(ask_router)
app.include_router(state_router)
app.include_router(jobs_router)
app.include_router(skills_router)
app.include_router(conflicts_router)
app.include_router(onboard_router)
app.include_router(onboarding_router)
app.include_router(alerts_router)
app.include_router(slack_router)

# ── Slack MCP router (events, canvas, slash commands) ─────────────────────────
from integrations.slack_routes import create_slack_router
from agents import ingest_agent, struct_agent, exec_agent, feedback_agent
from agents.extraction import _chunk_text
from core.logging import _utc_now_iso, _debug_event
from core.security import _is_sensitive
from jobs.handlers import _enqueue_slack_realtime_ingest

_MAX_EXTRACTION_CHARS = int(os.getenv("MAX_EXTRACTION_CHARS", "8000"))
app.include_router(create_slack_router(
    ingest_agent=ingest_agent,
    struct_agent=struct_agent,
    exec_agent=exec_agent,
    feedback_agent=feedback_agent,
    chunk_text=_chunk_text,
    max_extraction_chars=_MAX_EXTRACTION_CHARS,
    utc_now_iso=_utc_now_iso,
    debug_event=_debug_event,
    is_sensitive=_is_sensitive,
    enqueue_realtime_ingest=_enqueue_slack_realtime_ingest,
))

# ── Startup: Slack web poller ──────────────────────────────────────────────────
@app.on_event("startup")
async def _start_slack_poller() -> None:
    from config import SLACK_POLLER_ENABLED, SLACK_POLLER_INTERVAL
    if not SLACK_POLLER_ENABLED:
        print("[BrainOS] slack web poller: disabled via SLACK_POLLER_ENABLED")
        return
    from integrations.slack_routes import _run_slack_poller, load_slack_config
    from jobs.handlers import _enqueue_slack_realtime_ingest
    from core.logging import _debug_event
    asyncio.create_task(
        _run_slack_poller(
            config_loader=load_slack_config,
            enqueue_fn=_enqueue_slack_realtime_ingest,
            debug_event_fn=_debug_event,
            interval_s=SLACK_POLLER_INTERVAL,
        )
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
