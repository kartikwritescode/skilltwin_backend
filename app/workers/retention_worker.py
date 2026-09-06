import asyncio
from datetime import datetime, timezone
from app.core.logging import logger
from app.repositories.revision_repository import revision_repository
from app.repositories.learner_repository import learner_repository


class RetentionWorker:
    """
    Background worker that monitors learner retention risk decay curves,
    updates forgetting scores, and schedules spaced retrieval alerts.
    """

    def __init__(self):
        self._running = False

    async def run_decay_sweep(self):
        logger.info("Running retention decay calculation sweep...")
        # Inspect review items and increment decay for overdue cards
        due_items = await revision_repository.list_all()
        now = datetime.now(timezone.utc)
        for item in due_items:
            if item.due_at < now and item.retention_risk != "high":
                item.retention_risk = "high"
                await revision_repository.save(item)
                logger.info(f"Marked concept {item.concept_id} as high retention risk for user {item.user_id}")

    async def start_periodic_worker(self, interval_seconds: int = 3600):
        self._running = True
        logger.info(f"Retention background worker started (interval: {interval_seconds}s)")
        while self._running:
            try:
                await self.run_decay_sweep()
            except Exception as e:
                logger.error(f"Error in retention worker sweep: {e}")
            await asyncio.sleep(interval_seconds)

    def stop(self):
        self._running = False


retention_worker = RetentionWorker()
