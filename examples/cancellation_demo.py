import asyncio


async def slow_consumer(lock: asyncio.Lock) -> None:
    async with lock:
        await asyncio.sleep(0.4)


async def waiting_consumer(lock: asyncio.Lock) -> None:
    await lock.acquire()
    try:
        await asyncio.sleep(0.15)
    finally:
        lock.release()


async def main() -> None:
    lock = asyncio.Lock()
    primary = asyncio.create_task(slow_consumer(lock), name="slow-consumer")
    secondary = asyncio.create_task(waiting_consumer(lock), name="waiting-consumer")
    await asyncio.sleep(0.05)
    secondary.cancel()
    await asyncio.gather(primary, secondary, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
