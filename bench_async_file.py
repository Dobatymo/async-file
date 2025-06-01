import asyncio
from argparse import ArgumentParser
from collections import defaultdict
from time import time

import aiofiles
from rich.console import Console
from rich.table import Table

from async_file.async_file import MyProactorEventLoop
from async_file.async_file import readall as iocp_read


async def aiofiles_read(path: str, chunk_size: int) -> int:
    num_chunks = 0
    async with aiofiles.open(path, "rb") as fr:
        while True:
            data = await fr.read(chunk_size)
            if not data:
                break
            num_chunks += 1
    return num_chunks


def sync_read(path: str, chunk_size: int) -> int:
    num_chunks = 0
    with open(path, "rb") as fr:
        while True:
            data = fr.read(chunk_size)
            if not data:
                break
            num_chunks += 1
    return num_chunks


async def bench(path: str, chunk_size: int) -> dict:
    start = time()
    sync_read(path, chunk_size)
    t1 = time() - start

    start = time()
    await iocp_read(path, chunk_size)
    t2 = time() - start

    start = time()
    await aiofiles_read(path, chunk_size)
    t3 = time() - start

    return {"sync read": t1, "asyncio read": t2, "aiofiles read": t3}


def print_table(d: dict[int, dict[str, float]]) -> None:
    table = Table(title="async file read benchmark")

    table.add_column("chunk-size/method")
    for names in d.values():
        for name in names:
            table.add_column(name)
        break

    for chunk_size, names in d.items():
        vals = [f"{t:.02f}" for t in names.values()]
        table.add_row(str(chunk_size), *vals)

    console = Console()
    console.print(table)


def main():
    DEFAULT_CHUNK_SIZES = (1024, 64 * 1024, 1024 * 1024)

    parser = ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--chunk-sizes", nargs="+", default=DEFAULT_CHUNK_SIZES, type=int)
    args = parser.parse_args()

    # warmup
    sync_read(args.path, 64 * 1024)

    results = defaultdict(dict)
    for chunk_size in args.chunk_sizes:
        d = asyncio.run(
            bench(args.path, chunk_size),
            loop_factory=MyProactorEventLoop,
        )
        for name, duration in d.items():
            results[chunk_size][name] = duration

    print_table(results)


if __name__ == "__main__":
    main()
