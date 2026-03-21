from __future__ import annotations

import asyncio

from pyroscope.runtime import AsyncioTracer
from pyroscope.session import SessionStore


def test_traces_task_lifecycle_and_blocking() -> None:
    store = SessionStore("runtime")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def sample() -> None:
        queue: asyncio.Queue[int] = asyncio.Queue()

        async def worker() -> None:
            item = await queue.get()
            await asyncio.sleep(0.01)
            queue.task_done()
            if item == 1:
                return

        task = asyncio.create_task(worker(), name="worker")
        await queue.put(1)
        await queue.join()
        await task

    try:
        asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    events = store.events()
    kinds = {event["kind"] for event in events}
    assert "task.create" in kinds
    assert "task.start" in kinds
    assert "task.block" in kinds
    assert "task.end" in kinds
    assert store.tasks()
