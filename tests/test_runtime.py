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
    assert child_task["metadata"]["queue_size"] == 0
    assert child_task["metadata"]["queue_maxsize"] == 0
    detailed_child = store.task(child_task["task_id"])
    assert detailed_child is not None
    stack = detailed_child["stack"]
    assert stack["frames"]
    assert all(not frame.startswith("File ") for frame in stack["frames"])
    assert any(" in " in frame for frame in stack["frames"])
    assert any("await" in frame or "return" in frame for frame in stack["frames"])


def test_marks_external_cancellation_while_child_waits_on_event_with_live_state() -> None:
    store = SessionStore("event-cancel")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def child_worker(event: asyncio.Event) -> None:
        await event.wait()

    async def parent_worker() -> None:
        event = asyncio.Event()
        child = asyncio.create_task(child_worker(event), name="event-child")
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
    child_task = next(task for task in tasks if task["name"] == "event-child")

    assert child_task["state"] == "CANCELLED"
    assert child_task["cancellation_origin"] == "parent_task"
    assert child_task["metadata"]["blocked_reason"] == "event_wait"
    assert child_task["metadata"]["blocked_resource_id"].startswith("event:")
    assert child_task["metadata"]["event_is_set"] is False


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


def test_traces_asyncio_timeout_context_manager() -> None:
    store = SessionStore("timeout-cm")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def sample() -> None:
        try:
            async with asyncio.timeout(0.01):
                await asyncio.sleep(1.0)
        except TimeoutError:
            pass

    try:
        asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    events = store.events()
    kinds = {e["kind"] for e in events}
    assert "task.block" in kinds
    assert "task.unblock" in kinds

    block_events = [e for e in events if e["kind"] == "task.block"]
    timeout_blocks = [e for e in block_events if e.get("reason") == "timeout_cm"]
    assert timeout_blocks, "Expected task.block with reason=timeout_cm"

    # The block event must carry timeout_seconds metadata
    block = timeout_blocks[0]
    assert block.get("metadata", {}).get("timeout_seconds") is not None
    assert block["resource_id"] == "timeout_cm"

    # Matching unblock event
    unblock_events = [
        e
        for e in events
        if e["kind"] == "task.unblock" and e.get("reason") == "timeout_cm"
    ]
    assert unblock_events, "Expected task.unblock with reason=timeout_cm"

    # Main task completes as DONE (TimeoutError is caught by user code)
    tasks = store.tasks()
    main_task = next(t for t in tasks if t["metadata"].get("task_role") == "main")
    assert main_task["state"] == "DONE"


def test_traces_condition_wait_and_notify() -> None:
    store = SessionStore("condition")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def sample() -> None:
        cond: asyncio.Condition = asyncio.Condition()
        ready: list[bool] = []

        async def waiter() -> None:
            async with cond:
                await cond.wait()
                ready.append(True)

        async def notifier() -> None:
            await asyncio.sleep(0.01)
            async with cond:
                cond.notify_all()

        t = asyncio.create_task(waiter(), name="cond-waiter")
        await notifier()
        await t

    try:
        asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    events = store.events()
    kinds = {e["kind"] for e in events}
    # Condition.wait should produce a block/unblock pair
    assert "task.block" in kinds
    assert "task.unblock" in kinds

    block_events = [e for e in events if e["kind"] == "task.block"]
    condition_blocks = [e for e in block_events if e.get("reason") == "condition_wait"]
    assert condition_blocks, "Expected at least one condition_wait block event"

    resource_ids = {e.get("resource_id") for e in condition_blocks}
    assert any(rid is not None and rid.startswith("condition:") for rid in resource_ids)


def test_traces_asyncio_barrier_wait() -> None:
    store = SessionStore("barrier")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def sample() -> None:
        barrier = asyncio.Barrier(2)

        async def participant(name: str) -> None:
            await barrier.wait()

        t1 = asyncio.create_task(participant("p1"), name="barrier-p1")
        t2 = asyncio.create_task(participant("p2"), name="barrier-p2")
        await asyncio.gather(t1, t2)

    try:
        asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    events = store.events()
    block_events = [e for e in events if e["kind"] == "task.block"]
    barrier_blocks = [e for e in block_events if e.get("reason") == "barrier_wait"]
    assert barrier_blocks, "Expected task.block events with reason=barrier_wait"

    resource_ids = {e.get("resource_id") for e in barrier_blocks}
    assert any(rid is not None and rid.startswith("barrier:") for rid in resource_ids)

    # metadata should include barrier parties count
    first = barrier_blocks[0]
    assert first.get("metadata", {}).get("barrier_parties") is not None


def test_traces_asyncio_shield_marks_inner_task_as_shielded() -> None:
    store = SessionStore("shield")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def sample() -> None:
        async def long_work() -> int:
            await asyncio.sleep(0.1)
            return 42

        task = asyncio.create_task(long_work(), name="shielded-worker")
        current = asyncio.current_task()
        assert current is not None
        asyncio.get_running_loop().call_later(0.01, current.cancel)
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            pass
        # shielded task should still complete
        await task

    try:
        asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    events = store.events()
    shield_events = [e for e in events if e["kind"] == "task.shield"]
    assert shield_events, "Expected task.shield event"
    assert any(
        e.get("metadata", {}).get("shielded_task_name") == "shielded-worker"
        for e in shield_events
    )

    tasks = store.tasks()
    inner_task = next(t for t in tasks if t["name"] == "shielded-worker")
    assert inner_task["metadata"].get("shielded") is True
    assert inner_task["state"] == "DONE"


def test_headless_summary_includes_cancellation_cascade_from_taskgroup() -> None:
    store = SessionStore("cascade-headless")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def failing_child() -> None:
        await asyncio.sleep(0.01)
        raise RuntimeError("boom")

    async def long_child() -> None:
        await asyncio.sleep(0.5)

    async def sample() -> None:
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(failing_child(), name="failing")
                group.create_task(long_child(), name="long-a")
                group.create_task(long_child(), name="long-b")
        except* RuntimeError:
            pass

    try:
        asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    summary = store.headless_summary()
    cancellation_items = summary["cancellation_insights"]
    kinds = {item["kind"] for item in cancellation_items}
    assert "cancellation_cascade" in kinds, (
        f"Expected cancellation_cascade in headless cancellation_insights, got {kinds}"
    )


def test_detailed_resource_graph_includes_task_names_and_states() -> None:
    store = SessionStore("resource-names")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def sample() -> None:
        lock = asyncio.Lock()
        holder_ready = asyncio.Event()
        waiter_done = asyncio.Event()

        async def holder() -> None:
            await lock.acquire()
            holder_ready.set()
            await waiter_done.wait()
            lock.release()

        async def waiter() -> None:
            await holder_ready.wait()
            await lock.acquire()
            lock.release()

        holder_task = asyncio.create_task(holder(), name="lock-holder")
        waiter_task = asyncio.create_task(waiter(), name="lock-waiter")

        await holder_ready.wait()
        await asyncio.sleep(0.01)  # ensure waiter is blocked on lock
        snapshot = store.resource_graph(detailed=True)
        waiter_done.set()
        await asyncio.gather(holder_task, waiter_task)
        return snapshot

    try:
        snapshot = asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    lock_row = next(item for item in snapshot if item["resource_id"].startswith("lock:"))

    # detailed view should include task names alongside task IDs
    assert "owner_task_names" in lock_row, "owner_task_names missing from detailed graph"
    assert "waiter_task_names" in lock_row, "waiter_task_names missing from detailed graph"
    assert "lock-holder" in lock_row["owner_task_names"]
    assert "lock-waiter" in lock_row["waiter_task_names"]


def test_traces_taskgroup_enter_exit_events() -> None:
    store = SessionStore("taskgroup-events")
    tracer = AsyncioTracer(store)
    tracer.install()

    async def sample() -> None:
        async with asyncio.TaskGroup() as group:
            group.create_task(asyncio.sleep(0.01), name="tg-child-a")
            group.create_task(asyncio.sleep(0.01), name="tg-child-b")

    try:
        asyncio.run(sample())
    finally:
        tracer.uninstall()
        store.mark_completed()

    events = store.events()
    kinds = [e["kind"] for e in events]

    assert "taskgroup.enter" in kinds, "Expected taskgroup.enter event"
    assert "taskgroup.exit" in kinds, "Expected taskgroup.exit event"

    enter_events = [e for e in events if e["kind"] == "taskgroup.enter"]
    exit_events = [e for e in events if e["kind"] == "taskgroup.exit"]

    # enter must carry a group_id
    assert all(e.get("metadata", {}).get("group_id") is not None for e in enter_events)
    # exit must carry group_id and exit_status
    assert all(e.get("metadata", {}).get("group_id") is not None for e in exit_events)
    assert all(e.get("metadata", {}).get("exit_status") is not None for e in exit_events)

    # normal exit — all tasks complete successfully
    normal_exits = [e for e in exit_events if e["metadata"]["exit_status"] == "normal"]
    assert normal_exits, "Expected at least one normal TaskGroup exit"
