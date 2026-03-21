import asyncio


async def failing_child() -> None:
    await asyncio.sleep(0.05)
    raise RuntimeError("boom")


async def long_child() -> None:
    await asyncio.sleep(1.0)


async def main() -> None:
    try:
        async with asyncio.TaskGroup() as group:
            group.create_task(failing_child(), name="failing-child")
            group.create_task(long_child(), name="long-child-a")
            group.create_task(long_child(), name="long-child-b")
    except* RuntimeError:
        pass


if __name__ == "__main__":
    asyncio.run(main())
