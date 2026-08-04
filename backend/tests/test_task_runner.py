from __future__ import annotations

import asyncio
import importlib
import threading

import pytest


def test_runner_processes_jobs_sequentially_and_survives_failure() -> None:
    try:
        runner_module = importlib.import_module("app.tasks.runner")
    except ModuleNotFoundError:
        pytest.fail("Local task runner is not implemented")

    class RecordingPipeline:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.completed = threading.Event()

        def process(self, job_id: str) -> None:
            self.calls.append(job_id)
            if job_id == "first":
                raise RuntimeError("expected failure")
            self.completed.set()

    async def scenario() -> list[str]:
        pipeline = RecordingPipeline()
        runner = runner_module.LocalTaskRunner(pipeline)
        await runner.start()
        await runner.enqueue("first")
        await runner.enqueue("second")
        completed = await asyncio.to_thread(pipeline.completed.wait, 2)
        await runner.stop()
        assert completed
        return pipeline.calls

    assert asyncio.run(scenario()) == ["first", "second"]


def test_runner_rejects_more_pending_jobs_than_configured() -> None:
    runner_module = importlib.import_module("app.tasks.runner")

    class Pipeline:
        def process(self, job_id: str) -> None:
            pass

    async def scenario() -> None:
        runner = runner_module.LocalTaskRunner(
            Pipeline(),
            max_pending_jobs=1,
        )
        await runner.enqueue("first")
        with pytest.raises(runner_module.QueueCapacityError):
            await runner.enqueue("second")

    asyncio.run(scenario())
