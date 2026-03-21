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
    tasks = store.tasks()
    assert tasks
    main_task = next(
        task for task in tasks if task["metadata"].get("task_role") == "main"
    )
    assert main_task["metadata"]["runtime_origin"] == "asyncio.run"
    assert main_task["state"] == "DONE"

    worker_task = next(task for task in tasks if task["name"] == "worker")
    assert worker_task["parent_task_id"] == main_task["task_id"]


def test_traces_taskgroup_cancellation_and_parent_relationships() -> None:
    store = SessionStore("taskgroup")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def failing_child() -> None:
        await asyncio.sleep(0.01)
        raise RuntimeError("boom")

    async def long_child() -> None:
        await asyncio.sleep(0.2)

    async def sample() -> None:
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(failing_child(), name="failing-child")
                group.create_task(long_child(), name="long-child-a")
                group.create_task(long_child(), name="long-child-b")
        except* RuntimeError:
            pass

    try:
        asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    tasks = store.tasks()
    assert len(tasks) >= 3

    runtime_tasks = [
        task
        for task in tasks
        if task["name"].startswith(("failing-child", "long-child"))
    ]
    assert len(runtime_tasks) == 3

    parent_ids = {task["parent_task_id"] for task in runtime_tasks}
    assert len(parent_ids) == 1
    assert None not in parent_ids
    parent_task_id = next(iter(parent_ids))

    parent_record = next(task for task in tasks if task["task_id"] == parent_task_id)
    assert sorted(parent_record["children"]) == sorted(
        [task["task_id"] for task in runtime_tasks]
    )

    parent_task = store.task(parent_task_id)
    assert parent_task is not None
    assert parent_task["state"] in {"RUNNING", "DONE"}
    assert sorted(parent_task["children"]) == sorted(
        [task["task_id"] for task in runtime_tasks]
    )

    states = {task["name"]: task["state"] for task in runtime_tasks}
    assert states["failing-child"] == "FAILED"
    assert "CANCELLED" in {states["long-child-a"], states["long-child-b"]}

    cancelled_tasks = [task for task in runtime_tasks if task["state"] == "CANCELLED"]
    assert cancelled_tasks
    failing_task_id = next(
        task["task_id"] for task in runtime_tasks if task["name"] == "failing-child"
    )
    for task in cancelled_tasks:
        assert task["cancelled_by_task_id"] == failing_task_id
        assert task["cancellation_origin"] == "sibling_failure"

    insight_kinds = {item["kind"] for item in store.insights()}
    assert "task_error" in insight_kinds
    assert "cancellation_cascade" in insight_kinds


def test_marks_root_task_cancellation_as_external() -> None:
    store = SessionStore("cancellation-origins")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def sample() -> None:
        current = asyncio.current_task()
        assert current is not None
        asyncio.get_running_loop().call_soon(current.cancel)
        await asyncio.sleep(1)

    try:
        try:
            asyncio.run(sample())
        except asyncio.CancelledError:
            pass
    finally:
        tracer.uninstall()
        store.mark_completed()

    cancelled_root_tasks = [
        task
        for task in store.tasks()
        if task["state"] == "CANCELLED" and task["parent_task_id"] is None
    ]
    assert cancelled_root_tasks
    root_task = cancelled_root_tasks[0]
    assert root_task["cancelled_by_task_id"] is None
    assert root_task["cancellation_origin"] == "external"


def test_marks_explicit_child_cancel_as_parent_task_cancellation() -> None:
    store = SessionStore("parent-cancel")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def child_worker() -> None:
        await asyncio.sleep(1)

    async def parent_worker() -> None:
        child = asyncio.create_task(child_worker(), name="child-worker")
        await asyncio.sleep(0.01)
        child.cancel()
        try:
            await child
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(parent_worker())
    finally:
        tracer.uninstall()
        store.mark_completed()

    tasks = store.tasks()
    child_task = next(task for task in tasks if task["name"] == "child-worker")
    parent_task = next(
        task for task in tasks if task["task_id"] == child_task["parent_task_id"]
    )

    assert child_task["state"] == "CANCELLED"
    assert child_task["cancelled_by_task_id"] == parent_task["task_id"]
    assert child_task["cancellation_origin"] == "parent_task"
