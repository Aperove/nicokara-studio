from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any


logger = logging.getLogger(__name__)


class QueueCapacityError(RuntimeError):
    """Raised when the local processing queue is full."""


class LocalTaskRunner:
    def __init__(
        self,
        pipeline: Any,
        *,
        max_pending_jobs: int = 4,
    ) -> None:
        self.pipeline = pipeline
        self.queue: asyncio.Queue[str] = asyncio.Queue(
            maxsize=max_pending_jobs
        )
        self._worker_task: asyncio.Task[None] | None = None

    @property
    def can_accept(self) -> bool:
        return not self.queue.full()

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._worker())

    async def enqueue(self, job_id: str) -> None:
        try:
            self.queue.put_nowait(job_id)
        except asyncio.QueueFull as exc:
            raise QueueCapacityError(
                "The processing queue is full"
            ) from exc

    async def stop(self) -> None:
        await self.queue.join()
        if self._worker_task is not None:
            self._worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await asyncio.to_thread(self.pipeline.process, job_id)
            except Exception:
                logger.exception("Background processing failed for job %s", job_id)
            finally:
                self.queue.task_done()
