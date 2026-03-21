import asyncio


async def worker(name: str, jobs: asyncio.Queue[int]) -> None:
    while True:
        item = await jobs.get()
        try:
            if item < 0:
                return
            await asyncio.sleep(0.05 + item * 0.01)
        finally:
            jobs.task_done()


async def main() -> None:
    queue: asyncio.Queue[int] = asyncio.Queue()
    workers = [asyncio.create_task(worker(f"worker-{idx}", queue), name=f"worker-{idx}") for idx in range(3)]
    for job in range(8):
        await queue.put(job)
    for _ in workers:
        await queue.put(-1)
    await queue.join()
    await asyncio.gather(*workers, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
