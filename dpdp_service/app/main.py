"""ConsentBridge (DPDP Compliance Platform) service entrypoint. Standalone — see package
docstring, Finverge_DPDP_HLD_v1.0.docx Sec. 8 (Deployment Topology).

Run locally (no Docker required):
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8110

Then: http://localhost:8110/docs
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import SessionLocal, init_db
from app.regulatory_watch import check_all_sources
from app.routes import router
from app.routes_ai import router as ai_router
from app.routes_auth import router as auth_router
from app.routes_regulatory_watch import router as regulatory_watch_router
from app.routes_tenants import router as tenants_router
from app.routes_webhooks import router as webhooks_router
from app.tenant_keys import process_due_rotations
from app.webhooks import process_due_deliveries

logger = logging.getLogger("dpdp.main")

WEBHOOK_RETRY_LOOP_INTERVAL_SECONDS = 30
# Government sites, not our own infra — checked far less often than webhook
# retries, and only on active sources (a no-op tick costs nothing when the
# platform_admin hasn't configured any yet).
REGULATORY_WATCH_LOOP_INTERVAL_SECONDS = 1800  # 30 min
# Key rotation is scheduled in days (app/tenant_keys.py), so checking
# hourly is more than frequent enough — no tenant's rotate_by can be
# missed by more than an hour, and an hourly tick costs nothing when
# nothing is due.
API_KEY_ROTATION_LOOP_INTERVAL_SECONDS = 3600  # 1 hour


async def _webhook_retry_loop():
    """Dev-grade in-process scheduler for webhook retry-with-backoff (FSD
    Sec. 5.4, see app/webhooks.py's module docstring for the honest scope
    note — this is not durable queue infra). Runs for the life of the
    process; a real deployment can instead point an external cron at
    POST /webhooks/deliveries/process-due and drop this loop."""
    while True:
        await asyncio.sleep(WEBHOOK_RETRY_LOOP_INTERVAL_SECONDS)
        try:
            db = SessionLocal()
            try:
                processed = await asyncio.to_thread(process_due_deliveries, db)
                if processed:
                    logger.info("Webhook retry loop processed %d due delivery attempt(s).", processed)
            finally:
                db.close()
        except Exception:
            logger.exception("Webhook retry loop iteration failed; will retry on the next tick.")


async def _regulatory_watch_loop():
    """Dev-grade in-process scheduler for the Regulatory-Change Watch
    Agent (BRD Sec. 6.6, see app/regulatory_watch.py's honest-scope
    docstring). A real deployment can instead point an external cron at
    POST /regulatory-watch/check-all and drop this loop."""
    while True:
        await asyncio.sleep(REGULATORY_WATCH_LOOP_INTERVAL_SECONDS)
        try:
            db = SessionLocal()
            try:
                summary = await asyncio.to_thread(check_all_sources, db)
                if summary["new_alerts"]:
                    logger.info("Regulatory watch loop found %d new change(s).", summary["new_alerts"])
            finally:
                db.close()
        except Exception:
            logger.exception("Regulatory watch loop iteration failed; will retry on the next tick.")


async def _api_key_rotation_loop():
    """Dev-grade in-process scheduler for scheduled/automatic tenant
    API-key rotation (app/tenant_keys.py). A real deployment can instead
    point an external cron at POST /tenants/rotate-due-api-keys and drop
    this loop."""
    while True:
        await asyncio.sleep(API_KEY_ROTATION_LOOP_INTERVAL_SECONDS)
        try:
            db = SessionLocal()
            try:
                rotated = await asyncio.to_thread(process_due_rotations, db)
                if rotated:
                    logger.info("API-key rotation loop force-rotated %d tenant key(s) past due.", rotated)
            finally:
                db.close()
        except Exception:
            logger.exception("API-key rotation loop iteration failed; will retry on the next tick.")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()  # dev convenience; swap for Alembic before production
    retry_task = asyncio.create_task(_webhook_retry_loop())
    watch_task = asyncio.create_task(_regulatory_watch_loop())
    key_rotation_task = asyncio.create_task(_api_key_rotation_loop())
    try:
        yield
    finally:
        retry_task.cancel()
        watch_task.cancel()
        key_rotation_task.cancel()


app = FastAPI(
    title="ConsentBridge",
    description="ConsentBridge — Finverge's DPDP Compliance Platform. Consent Management Engine, "
                 "Data Minimization & Masking, Grievance/DPO module (Phase 1); multi-tenant "
                 "onboarding & metering (Phase 2); deterministic AI-native capability layer (Phase 3), "
                 "now including the Regulatory-Change Watch Agent (BRD Sec. 6.6), Consent Pattern "
                 "Analytics (Sec. 6.10), Grievance Sentiment & Trust Scoring (Sec. 6.11), and Automated "
                 "Breach Simulation & Stress Testing (Sec. 6.12); outbound webhooks (FSD Sec. 5.4). "
                 "See BRD Sec. 12 for phase scope.",
    version="0.7.0",
    lifespan=lifespan,
)

# Standalone dev convenience — diy-portal (5173) and Fraud360 frontend (5180)
# both call this service directly from the browser during Phase 1 dogfood
# (HLD Sec. 7); CORS stays open only because nothing fronts this service yet.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(router)
app.include_router(tenants_router)
app.include_router(ai_router)
app.include_router(auth_router)
app.include_router(webhooks_router)
app.include_router(regulatory_watch_router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "dpdp-consent-platform"}
