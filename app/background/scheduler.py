from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.database.database import Database

logger = logging.getLogger("app.background.scheduler")


class BackgroundTaskManager:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _poll(self) -> None:
        while True:
            try:
                for item in self.database.due_schedules(datetime.now(timezone.utc).isoformat()):
                    result = f"Reminder: {item['title']}"
                    self.database.complete_schedule(item["id"], result)
                    self.database.add_activity("Background task completed", result)
            except Exception as exc:
                logger.warning("Background scheduler poll encountered error: %s", exc)
            await asyncio.sleep(15)
