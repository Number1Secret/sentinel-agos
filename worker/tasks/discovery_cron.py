"""
Discovery SDR Cron Job

Autonomous follow-up scheduler that scans discovery_negotiations
for leads with due follow-up actions and pushes them to the
discovery_queue for processing.

Usage:
    python -m worker.tasks.discovery_cron

Runs as a one-shot scan (designed to be called by a cron scheduler
like Render Cron Jobs every 15 minutes).
"""
import json
from datetime import datetime

import redis
import structlog

from config import settings
from services.supabase import SupabaseService

logger = structlog.get_logger()

# Safety limits
MAX_LEADS_PER_RUN = 50
DEDUP_KEY_PREFIX = "sdr_cron:queued:"
DEDUP_TTL_SECONDS = 900  # 15 minutes


def run_sdr_cron():
    """
    Main cron function: scan for due follow-ups and queue them.

    Queries discovery_negotiations for rows where:
    - next_action_at <= NOW()
    - sdr_state NOT IN ('completed')
    - Associated lead status is 'presenting' or 'negotiating'

    For each match, pushes a job to discovery_queue with trigger='sdr_cron'.
    Uses Redis SET for deduplication to prevent double-queuing.
    """
    logger.info("SDR Cron: Starting scan")

    db = SupabaseService(use_admin=True)
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)

    try:
        # Query for due follow-ups
        now = datetime.utcnow().isoformat()
        response = db.client.table("discovery_negotiations").select(
            "lead_id, sdr_state, next_action_at, total_touches"
        ).lte(
            "next_action_at", now
        ).not_.in_(
            "sdr_state", ["completed"]
        ).limit(MAX_LEADS_PER_RUN).execute()

        negotiations = response.data or []

        if not negotiations:
            logger.info("SDR Cron: No due follow-ups found")
            return

        logger.info(
            "SDR Cron: Found due follow-ups",
            count=len(negotiations),
        )

        queued_count = 0
        skipped_count = 0

        for neg in negotiations:
            lead_id = neg.get("lead_id")
            if not lead_id:
                continue

            # Deduplication: check if already queued recently
            dedup_key = f"{DEDUP_KEY_PREFIX}{lead_id}"
            if redis_client.exists(dedup_key):
                skipped_count += 1
                continue

            # Verify lead is still in a valid discovery status
            lead = db.client.table("leads").select("status").eq(
                "id", lead_id
            ).maybe_single().execute()

            if not lead.data:
                continue

            lead_status = lead.data.get("status")
            if lead_status not in ("presenting", "negotiating"):
                logger.debug(
                    "SDR Cron: Lead no longer in discovery",
                    lead_id=lead_id,
                    status=lead_status,
                )
                continue

            # Push to discovery_queue
            job_data = {
                "lead_id": lead_id,
                "trigger": "sdr_cron",
            }
            redis_client.rpush("discovery_queue", json.dumps(job_data))

            # Set dedup key with TTL
            redis_client.setex(dedup_key, DEDUP_TTL_SECONDS, "1")

            queued_count += 1

        logger.info(
            "SDR Cron: Scan complete",
            queued=queued_count,
            skipped_dedup=skipped_count,
            total_due=len(negotiations),
        )

    except Exception as e:
        logger.exception("SDR Cron: Failed", error=str(e))
        raise


if __name__ == "__main__":
    run_sdr_cron()
