"""Demo: multiple tasks sharing a semaphore and a lock."""
import asyncio


async def critical_section(
    lock: asyncio.Lock, semaphore: asyncio.Semaphore, worker_id: int
) -> None:
    async with semaphore:
        print(f"worker-{worker_id}: acquired semaphore slot")
        async with lock:
            print(f"worker-{worker_id}: inside critical section")
            await asyncio.sleep(0.05)
        print(f"worker-{worker_id}: released lock")
    print(f"worker-{worker_id}: released semaphore slot")


async def main() -> None:
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(2)
    workers = [
        asyncio.create_task(
            critical_section(lock, semaphore, i), name=f"worker-{i}"
        )
        for i in range(5)
    ]
    await asyncio.gather(*workers)


if __name__ == "__main__":
    asyncio.run(main())
