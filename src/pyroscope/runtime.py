from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import threading
import time
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from .model import Event, StackSnapshot
from .session import SessionStore


class AsyncioTracer:
    def __init__(self, store: SessionStore) -> None:
        self.store = store
        self._installed = False
        self._originals: dict[tuple[Any, str], Any] = {}
        self._lock = threading.RLock()

    def install(self) -> None:
        with self._lock:
            if self._installed:
                return
            self._patch(asyncio, "run", self._wrap_asyncio_run(asyncio.run))
            self._patch(
                asyncio, "create_task", self._wrap_create_task(asyncio.create_task)
            )
            self._patch(
                asyncio.BaseEventLoop,
                "create_task",
                self._wrap_loop_create_task(asyncio.BaseEventLoop.create_task),
            )
            self._patch(
                asyncio,
                "sleep",
                self._wrap_async_function(
                    asyncio.sleep, "sleep", lambda _args, _kwargs: "sleep"
                ),
            )
            self._patch(
                asyncio,
                "gather",
                self._wrap_async_function(
                    asyncio.gather, "gather", lambda _args, _kwargs: "gather"
                ),
            )
            self._patch(
                asyncio,
                "wait",
                self._wrap_async_function(
                    asyncio.wait, "wait", lambda _args, _kwargs: "wait"
                ),
            )
            self._patch(
                asyncio.Queue,
                "get",
                self._wrap_method(
                    asyncio.Queue.get,
                    "queue_get",
                    lambda args, _kwargs: f"queue:{id(args[0])}",
                ),
            )
            self._patch(
                asyncio.Queue,
                "put",
                self._wrap_method(
                    asyncio.Queue.put,
                    "queue_put",
                    lambda args, _kwargs: f"queue:{id(args[0])}",
                ),
            )
            self._patch(
                asyncio.Lock,
                "acquire",
                self._wrap_method(
                    asyncio.Lock.acquire,
                    "lock_acquire",
                    lambda args, _kwargs: f"lock:{id(args[0])}",
                ),
            )
            self._patch(
                asyncio.Semaphore,
                "acquire",
                self._wrap_method(
                    asyncio.Semaphore.acquire,
                    "semaphore_acquire",
                    lambda args, _kwargs: f"semaphore:{id(args[0])}",
                ),
            )
            self._patch(
                asyncio.Event,
                "wait",
                self._wrap_method(
                    asyncio.Event.wait,
                    "event_wait",
                    lambda args, _kwargs: f"event:{id(args[0])}",
                ),
            )
            self._installed = True

    def uninstall(self) -> None:
        with self._lock:
            for (owner, attr), original in reversed(list(self._originals.items())):
                setattr(owner, attr, original)
            self._originals.clear()
            self._installed = False

    def _patch(self, owner: Any, attr: str, replacement: Any) -> None:
        key = (owner, attr)
        if key not in self._originals:
            self._originals[key] = getattr(owner, attr)
        setattr(owner, attr, replacement)

    def _wrap_asyncio_run(self, original: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(original)
        def wrapper(main: Awaitable[Any], *args: Any, **kwargs: Any) -> Any:
            async def instrumented() -> Any:
                loop = asyncio.get_running_loop()
                self._emit_event(
                    kind="runtime.loop", state="RUNNING", metadata={"loop_id": id(loop)}
                )
                return await main

            return original(instrumented(), *args, **kwargs)

        return wrapper

    def _wrap_create_task(
        self, original: Callable[..., asyncio.Task[Any]]
    ) -> Callable[..., asyncio.Task[Any]]:
        @functools.wraps(original)
        def wrapper(coro: Any, *args: Any, **kwargs: Any) -> asyncio.Task[Any]:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro, *args, **kwargs)
            return task

        return wrapper

    def _wrap_loop_create_task(
        self,
        original: Callable[..., asyncio.Task[Any]],
    ) -> Callable[..., asyncio.Task[Any]]:
        @functools.wraps(original)
        def wrapper(
            loop: asyncio.AbstractEventLoop,
            coro: Any,
            *args: Any,
            **kwargs: Any,
        ) -> asyncio.Task[Any]:
            parent = asyncio.current_task(loop=loop)
            parent_task_id = id(parent) if parent is not None else None
            task_name = self._task_name(coro, kwargs.get("name"))

            async def instrumented() -> Any:
                current = asyncio.current_task(loop=loop)
                task_id = id(current) if current is not None else None
                self._emit_event(
                    kind="task.start",
                    task_id=task_id,
                    task_name=task_name,
                    parent_task_id=parent_task_id,
                    state="RUNNING",
                )
                if current is not None:
                    self._emit_stack(current)
                try:
                    result = await coro
                except asyncio.CancelledError:
                    self._emit_event(
                        kind="task.cancel",
                        task_id=task_id,
                        task_name=task_name,
                        parent_task_id=parent_task_id,
                        cancelled_by_task_id=parent_task_id,
                        cancellation_origin=(
                            "parent_task" if parent_task_id is not None else "external"
                        ),
                        state="CANCELLED",
                        reason="cancelled",
                    )
                    raise
                except Exception as exc:
                    self._emit_event(
                        kind="task.error",
                        task_id=task_id,
                        task_name=task_name,
                        parent_task_id=parent_task_id,
                        state="FAILED",
                        reason=exc.__class__.__name__,
                        metadata={"error": repr(exc)},
                    )
                    if current is not None:
                        self._emit_stack(current)
                    raise
                else:
                    self._emit_event(
                        kind="task.end",
                        task_id=task_id,
                        task_name=task_name,
                        parent_task_id=parent_task_id,
                        state="DONE",
                    )
                    return result

            task = original(loop, instrumented(), *args, **kwargs)
            self._emit_event(
                kind="task.create",
                task_id=id(task),
                task_name=task_name,
                parent_task_id=parent_task_id,
                state="READY",
            )
            return task

        return wrapper

    def _wrap_async_function(
        self,
        original: Callable[..., Awaitable[Any]],
        reason: str,
        resource_factory: Callable[[tuple[Any, ...], dict[str, Any]], str | None],
    ) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(original)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            task = asyncio.current_task()
            task_id = id(task) if task is not None else None
            task_name = task.get_name() if task is not None else None
            resource_id = resource_factory(args, kwargs)
            self._emit_event(
                kind="task.block",
                task_id=task_id,
                task_name=task_name,
                state="BLOCKED",
                reason=reason,
                resource_id=resource_id,
            )
            try:
                return await original(*args, **kwargs)
            finally:
                self._emit_event(
                    kind="task.unblock",
                    task_id=task_id,
                    task_name=task_name,
                    state="RUNNING",
                    reason=reason,
                    resource_id=resource_id,
                )
                if task is not None:
                    self._emit_stack(task)

        return wrapper

    def _wrap_method(
        self,
        original: Callable[..., Awaitable[Any]],
        reason: str,
        resource_factory: Callable[[tuple[Any, ...], dict[str, Any]], str | None],
    ) -> Callable[..., Awaitable[Any]]:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            task = asyncio.current_task()
            task_id = id(task) if task is not None else None
            task_name = task.get_name() if task is not None else None
            resource_id = resource_factory(args, kwargs)
            self._emit_event(
                kind="task.block",
                task_id=task_id,
                task_name=task_name,
                state="BLOCKED",
                reason=reason,
                resource_id=resource_id,
            )
            try:
                return await original(*args, **kwargs)
            finally:
                self._emit_event(
                    kind="task.unblock",
                    task_id=task_id,
                    task_name=task_name,
                    state="RUNNING",
                    reason=reason,
                    resource_id=resource_id,
                )
                if task is not None:
                    self._emit_stack(task)

        return functools.wraps(original)(wrapper)

    def _emit_event(
        self,
        *,
        kind: str,
        task_id: int | None = None,
        task_name: str | None = None,
        state: str | None = None,
        reason: str | None = None,
        resource_id: str | None = None,
        parent_task_id: int | None = None,
        cancelled_by_task_id: int | None = None,
        cancellation_origin: str | None = None,
        stack_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = Event(
            session_id=self.store.session_id,
            seq=self.store.next_seq(),
            ts_ns=time.time_ns(),
            kind=kind,
            task_id=task_id,
            task_name=task_name,
            state=state,
            reason=reason,
            resource_id=resource_id,
            parent_task_id=parent_task_id,
            cancelled_by_task_id=cancelled_by_task_id,
            cancellation_origin=cancellation_origin,
            stack_id=stack_id,
            metadata=metadata or {},
        )
        self.store.append_event(event)

    def _emit_stack(self, task: asyncio.Task[Any]) -> None:
        frames = task.get_stack(limit=16)
        if not frames:
            frame_strings = traceback.format_stack(limit=12)
        else:
            frame_strings = []
            for frame in frames:
                frame_strings.extend(traceback.format_stack(frame, limit=1))
        stack_blob = "".join(frame_strings)
        stack_id = hashlib.sha1(stack_blob.encode("utf-8")).hexdigest()[:12]
        snapshot = StackSnapshot(
            stack_id=stack_id,
            task_id=id(task),
            ts_ns=time.time_ns(),
            frames=[line.rstrip() for line in frame_strings if line.strip()],
        )
        self.store.add_stack(snapshot)
        self._emit_event(
            kind="stack.snapshot",
            task_id=id(task),
            task_name=task.get_name(),
            state="RUNNING",
            stack_id=stack_id,
        )

    def _task_name(self, coro: Awaitable[Any], explicit_name: str | None) -> str:
        if explicit_name:
            return explicit_name
        if inspect.iscoroutine(coro):
            code = getattr(coro, "cr_code", None)
            if code is not None:
                return code.co_name
        return getattr(coro, "__qualname__", coro.__class__.__name__)
