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


def test_marks_wait_for_timeout_as_timeout_cancellation() -> None:
    store = SessionStore("wait-for-timeout")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def child_worker() -> None:
        await asyncio.sleep(1)

    async def sample() -> None:
        try:
            await asyncio.wait_for(child_worker(), timeout=0.01)
        except TimeoutError:
            pass

    try:
        asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    tasks = store.tasks()
    main_task = next(
        task for task in tasks if task["metadata"].get("task_role") == "main"
    )
    child_task = next(task for task in tasks if task["name"] == "child_worker")

    assert child_task["state"] == "CANCELLED"
    assert child_task["cancelled_by_task_id"] == main_task["task_id"]
    assert child_task["cancellation_origin"] == "timeout"
    assert child_task["metadata"]["timeout_seconds"] == 0.01


def test_marks_parent_cancellation_while_child_waits_on_queue() -> None:
    store = SessionStore("queue-cancel")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def child_worker(queue: asyncio.Queue[int]) -> None:
        await queue.get()

    async def parent_worker() -> None:
        queue: asyncio.Queue[int] = asyncio.Queue()
        child = asyncio.create_task(child_worker(queue), name="queue-child")
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
    child_task = next(task for task in tasks if task["name"] == "queue-child")

    assert child_task["state"] == "CANCELLED"
    assert child_task["cancellation_origin"] == "parent_task"
    assert child_task["metadata"]["blocked_reason"] == "queue_get"
    assert child_task["metadata"]["blocked_resource_id"].startswith("queue:")
    detailed_child = store.task(child_task["task_id"])
    assert detailed_child is not None
    stack = detailed_child["stack"]
    assert stack["frames"]
    assert all(not frame.startswith("File ") for frame in stack["frames"])
    assert any(" in " in frame for frame in stack["frames"])
    assert any("await" in frame or "return" in frame for frame in stack["frames"])


def test_marks_external_cancellation_while_root_waits_on_lock() -> None:
    store = SessionStore("lock-cancel")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def sample() -> None:
        lock = asyncio.Lock()
        await lock.acquire()
        current = asyncio.current_task()
        assert current is not None
        asyncio.get_running_loop().call_later(0.01, current.cancel)
        try:
            await lock.acquire()
        finally:
            lock.release()

    try:
        try:
            asyncio.run(sample())
        except asyncio.CancelledError:
            pass
    finally:
        tracer.uninstall()
        store.mark_completed()

    root_task = next(
        task
        for task in store.tasks()
        if task["state"] == "CANCELLED" and task["parent_task_id"] is None
    )
    assert root_task["cancellation_origin"] == "external"
    assert root_task["metadata"]["blocked_reason"] == "lock_acquire"
    assert root_task["metadata"]["blocked_resource_id"].startswith("lock:")


def test_tracks_lock_owner_in_detailed_resource_graph_while_waiter_is_blocked() -> None:
    store = SessionStore("lock-owner-tracking")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def sample() -> None:
        lock = asyncio.Lock()
        holder_ready = asyncio.Event()
        waiter_attempting = asyncio.Event()
        release_holder = asyncio.Event()
        resource_snapshot = None
        waiter_snapshot = None

        async def holder() -> None:
            await lock.acquire()
            holder_ready.set()
            await release_holder.wait()
            lock.release()

        async def waiter() -> None:
            await holder_ready.wait()
            waiter_attempting.set()
            await lock.acquire()
            lock.release()

        waiter_task = asyncio.create_task(waiter(), name="lock-waiter")
        holder_task = asyncio.create_task(holder(), name="lock-holder")

        await waiter_attempting.wait()
        await asyncio.sleep(0.01)
        resource_snapshot = store.resource_graph(detailed=True)
        waiter_snapshot = store.task(id(waiter_task))
        release_holder.set()
        await asyncio.gather(holder_task, waiter_task)
        return resource_snapshot, waiter_snapshot

    try:
        resource_snapshot, waiter_snapshot = asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    assert resource_snapshot is not None
    lock_row = next(item for item in resource_snapshot if item["resource_id"].startswith("lock:"))
    assert len(lock_row["owner_task_ids"]) == 1
    assert len(lock_row["waiter_task_ids"]) == 1
    assert waiter_snapshot is not None
    assert waiter_snapshot["metadata"]["owner_task_ids"] == lock_row["owner_task_ids"]


def test_tracks_semaphore_owner_in_detailed_resource_graph_while_waiter_is_blocked() -> None:
    store = SessionStore("semaphore-owner-tracking")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def sample() -> None:
        semaphore = asyncio.Semaphore(1)
        holder_ready = asyncio.Event()
        waiter_attempting = asyncio.Event()
        release_holder = asyncio.Event()
        resource_snapshot = None
        waiter_snapshot = None

        async def holder() -> None:
            await semaphore.acquire()
            holder_ready.set()
            await release_holder.wait()
            semaphore.release()

        async def waiter() -> None:
            await holder_ready.wait()
            waiter_attempting.set()
            await semaphore.acquire()
            semaphore.release()

        waiter_task = asyncio.create_task(waiter(), name="sem-waiter")
        holder_task = asyncio.create_task(holder(), name="sem-holder")

        await waiter_attempting.wait()
        await asyncio.sleep(0.01)
        resource_snapshot = store.resource_graph(detailed=True)
        waiter_snapshot = store.task(id(waiter_task))
        release_holder.set()
        await asyncio.gather(holder_task, waiter_task)
        return resource_snapshot, waiter_snapshot

    try:
        resource_snapshot, waiter_snapshot = asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    assert resource_snapshot is not None
    semaphore_row = next(
        item
        for item in resource_snapshot
        if item["resource_id"].startswith("semaphore:")
    )
    assert len(semaphore_row["owner_task_ids"]) == 1
    assert len(semaphore_row["waiter_task_ids"]) == 1
    assert waiter_snapshot is not None
    assert waiter_snapshot["metadata"]["owner_task_ids"] == semaphore_row["owner_task_ids"]
