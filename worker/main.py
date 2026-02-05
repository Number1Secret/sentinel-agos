"""
Sentinel Background Worker - Multi-Queue Support

Processes jobs from Redis queues for different rooms:
- audit_queue: Legacy Scout audits (backward compatibility)
- triage_queue: Room 1 - Fast-pass URL scanning
- architect_queue: Room 2 - Mockup generation

Usage:
    python -m worker.main --queue triage_queue
    python -m worker.main --queue architect_queue
    python -m worker.main  # defaults to audit_queue for backward compat

Environment variables:
    WORKER_TYPE: 'audit', 'triage', or 'architect'
    WORKER_CONCURRENCY: Number of concurrent jobs (default: 1)
"""
import argparse
import asyncio
import json
import os
import signal
import sys
from typing import Optional, Callable, Awaitable

import redis
import structlog

from config import settings

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer() if settings.is_production else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Queue to processor mapping
QUEUE_PROCESSORS = {}


def register_processor(queue_name: str):
    """Decorator to register a job processor for a queue."""
    def decorator(func: Callable[[dict], Awaitable[None]]):
        QUEUE_PROCESSORS[queue_name] = func
        return func
    return decorator


# Import task processors (they register themselves)
# These imports must come after QUEUE_PROCESSORS is defined
def _load_processors():
    """Load all task processors."""
    from worker.tasks.audit import process_audit_job

    # Register the audit processor
    QUEUE_PROCESSORS["audit_queue"] = process_audit_job

    # Try to load triage processor
    try:
        from worker.tasks.triage import process_triage_job
        QUEUE_PROCESSORS["triage_queue"] = process_triage_job
    except ImportError:
        logger.debug("Triage processor not available")

    # Try to load architect processor
    try:
        from worker.tasks.architect import process_architect_job
        QUEUE_PROCESSORS["architect_queue"] = process_architect_job
    except ImportError:
        logger.debug("Architect processor not available")

    # Try to load discovery processor
    try:
        from worker.tasks.discovery import process_discovery_job
        QUEUE_PROCESSORS["discovery_queue"] = process_discovery_job
    except ImportError:
        logger.debug("Discovery processor not available")


class Worker:
    """
    Background worker that processes jobs from Redis queues.

    Supports multiple queue types:
    - audit_queue: Legacy Scout audits
    - triage_queue: Room 1 - URL triage
    - architect_queue: Room 2 - Mockup generation
    """

    def __init__(
        self,
        queue_name: str = "audit_queue",
        redis_url: str = None,
        concurrency: int = 1
    ):
        self.queue_name = queue_name
        self.redis_url = redis_url or settings.redis_url
        self.concurrency = concurrency
        self.redis: Optional[redis.Redis] = None
        self.running = False
        self.current_jobs: list = []
        self._semaphore: Optional[asyncio.Semaphore] = None

    def connect(self) -> None:
        """Connect to Redis."""
        self.redis = redis.from_url(self.redis_url, decode_responses=True)
        logger.info(
            "Connected to Redis",
            url=self.redis_url.split("@")[-1],
            queue=self.queue_name
        )

    def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self.redis:
            self.redis.close()
            self.redis = None
            logger.info("Disconnected from Redis")

    def get_processor(self) -> Callable[[dict], Awaitable[None]]:
        """Get the processor function for this worker's queue."""
        if self.queue_name not in QUEUE_PROCESSORS:
            raise ValueError(
                f"No processor registered for queue '{self.queue_name}'. "
                f"Available queues: {list(QUEUE_PROCESSORS.keys())}"
            )
        return QUEUE_PROCESSORS[self.queue_name]

    async def process_job(self, job_data: dict) -> None:
        """Process a single job using the appropriate processor."""
        job_id = job_data.get("audit_id") or job_data.get("lead_id") or "unknown"

        try:
            logger.info(
                "Starting job processing",
                queue=self.queue_name,
                job_id=job_id
            )
            self.current_jobs.append(job_id)

            processor = self.get_processor()
            await processor(job_data)

            logger.info(
                "Job completed successfully",
                queue=self.queue_name,
                job_id=job_id
            )

        except Exception as e:
            logger.error(
                "Job processing failed",
                queue=self.queue_name,
                job_id=job_id,
                error=str(e),
                exc_info=True,
            )

        finally:
            if job_id in self.current_jobs:
                self.current_jobs.remove(job_id)

    async def _process_with_semaphore(self, job_data: dict) -> None:
        """Process job with concurrency control."""
        async with self._semaphore:
            await self.process_job(job_data)

    async def run(self) -> None:
        """Main worker loop."""
        self.running = True
        self._semaphore = asyncio.Semaphore(self.concurrency)

        logger.info(
            "Worker started",
            queue=self.queue_name,
            concurrency=self.concurrency
        )

        pending_tasks = set()

        while self.running:
            try:
                # Block for up to 5 seconds waiting for a job
                result = self.redis.blpop(self.queue_name, timeout=5)

                if result:
                    _, job_json = result
                    job_data = json.loads(job_json)

                    # Create task for concurrent processing
                    task = asyncio.create_task(
                        self._process_with_semaphore(job_data)
                    )
                    pending_tasks.add(task)
                    task.add_done_callback(pending_tasks.discard)

                # Clean up completed tasks
                done = {t for t in pending_tasks if t.done()}
                pending_tasks -= done

            except redis.ConnectionError as e:
                logger.error("Redis connection error", error=str(e))
                await asyncio.sleep(5)

                try:
                    self.connect()
                except Exception:
                    pass

            except json.JSONDecodeError as e:
                logger.error("Invalid job data", error=str(e))

            except Exception as e:
                logger.error("Unexpected error in worker loop", error=str(e))
                await asyncio.sleep(1)

        # Wait for pending tasks to complete
        if pending_tasks:
            logger.info(f"Waiting for {len(pending_tasks)} pending tasks...")
            await asyncio.gather(*pending_tasks, return_exceptions=True)

        logger.info("Worker stopped", queue=self.queue_name)

    def stop(self) -> None:
        """Signal the worker to stop."""
        logger.info("Stopping worker...", queue=self.queue_name)
        self.running = False

    def handle_signal(self, signum, frame) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}")
        self.stop()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Sentinel Background Worker")
    parser.add_argument(
        "--queue",
        type=str,
        default=None,
        help="Queue name to process (audit_queue, triage_queue, architect_queue)"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Number of concurrent jobs to process"
    )
    return parser.parse_args()


def get_queue_name(args) -> str:
    """Determine queue name from args or environment."""
    # Command line takes precedence
    if args.queue:
        return args.queue

    # Check environment variable
    worker_type = os.getenv("WORKER_TYPE", "audit")
    queue_map = {
        "audit": "audit_queue",
        "triage": "triage_queue",
        "architect": "architect_queue",
        "discovery": "discovery_queue",
    }
    return queue_map.get(worker_type, "audit_queue")


def get_concurrency(args) -> int:
    """Determine concurrency from args or environment."""
    if args.concurrency:
        return args.concurrency

    return int(os.getenv("WORKER_CONCURRENCY", "1"))


def main():
    """Entry point for the worker."""
    args = parse_args()

    queue_name = get_queue_name(args)
    concurrency = get_concurrency(args)

    # Load processors
    _load_processors()

    worker = Worker(
        queue_name=queue_name,
        concurrency=concurrency
    )

    # Setup signal handlers
    signal.signal(signal.SIGINT, worker.handle_signal)
    signal.signal(signal.SIGTERM, worker.handle_signal)

    try:
        # Connect to Redis
        worker.connect()

        # Validate processor exists
        worker.get_processor()

        # Run the worker
        asyncio.run(worker.run())

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")

    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    finally:
        worker.disconnect()

    logger.info("Worker shutdown complete")
    sys.exit(0)


if __name__ == "__main__":
    main()
