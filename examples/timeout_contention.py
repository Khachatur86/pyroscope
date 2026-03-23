"""Demo: tasks racing a wait_for timeout against a shared queue."""
import asyncio


async def slow_producer(queue: asyncio.Queue) -> None:
    await asyncio.sleep(0.2)
    await queue.put("result")


async def consumer_with_timeout(queue: asyncio.Queue, timeout: float, name: str) -> None:
    try:
        result = await asyncio.wait_for(queue.get(), timeout=timeout)
        print(f"{name}: got {result!r}")
    except TimeoutError:
        print(f"{name}: timed out after {timeout}s")


async def main() -> None:
    queue: asyncio.Queue = asyncio.Queue()
    producer = asyncio.create_task(slow_producer(queue), name="slow-producer")
    fast_consumer = asyncio.create_task(
        consumer_with_timeout(queue, timeout=0.05, name="fast-consumer"),
        name="fast-consumer",
    )
    slow_consumer = asyncio.create_task(
        consumer_with_timeout(queue, timeout=0.5, name="slow-consumer"),
        name="slow-consumer",
    )
    await asyncio.gather(producer, fast_consumer, slow_consumer, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
