import asyncio
import ctypes
import os
from _overlapped import Overlapped
from _winapi import NULL
from asyncio.windows_events import IocpProactor
from asyncio.windows_utils import PipeHandle
from collections.abc import AsyncIterator, Awaitable, Buffer, Callable
from typing import Any, TypeAlias

ERROR_HANDLE_EOF = 38
FinishSocketFunc: TypeAlias = Callable[[Any, Any, Overlapped], Any]


class AsyncFile:
    def __init__(self, conn: PipeHandle, loop, offset: int = 0) -> None:
        self.conn = conn
        self.loop = loop
        self.offset = offset

    def tell(self) -> int:
        return self.offset

    def fileno(self) -> int:
        return self.conn.fileno()

    @property
    def closed(self) -> bool:
        return self.conn.handle is None

    def seek(self, offset, whence: int = os.SEEK_SET, /):
        if whence == os.SEEK_SET:
            self.offset = offset
        elif whence == os.SEEK_CUR:
            self.offset += offset
        elif whence == os.SEEK_END:
            raise ValueError("SEEK_END is not supported")
        else:
            raise ValueError(f"Unsupported whence: {whence}")

        return self.offset

    async def read(self, n: int) -> bytes:
        data = await self.loop.file_read(self.conn, n, self.offset)
        self.offset += len(data)
        return data

    async def write(self, data: Buffer) -> int:
        written = await self.loop.file_write(self.conn, data, self.offset)
        self.offset += written
        return written

    async def close(self) -> None:
        await self.loop.file_close(self.conn)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_ulonglong),
        ("InternalHigh", ctypes.c_ulonglong),
        ("Offset", ctypes.c_ulong),
        ("OffsetHigh", ctypes.c_ulong),
        ("hEvent", ctypes.c_void_p),
    ]


class MyIocpProactor(asyncio.IocpProactor):
    finish_socket_func: FinishSocketFunc
    _register_with_iocp: Callable[[PipeHandle], None]
    _result: Callable[[int], Awaitable[int]]
    _register: Callable[[Overlapped, PipeHandle, FinishSocketFunc], Awaitable[int]]

    def read_into(self, conn: PipeHandle, buf: Buffer, offset: int = 0) -> Awaitable[int]:
        self._register_with_iocp(conn)
        ov = Overlapped(NULL)
        overlapped_ptr = ctypes.cast(ov.address, ctypes.POINTER(OVERLAPPED))
        overlapped_ptr.contents.Offset = offset & 0xFFFF_FFFF
        overlapped_ptr.contents.OffsetHigh = (offset >> 32) & 0xFFFF_FFFF

        try:
            ov.ReadFileInto(conn.fileno(), buf)
        except BrokenPipeError:
            return self._result(0)

        return self._register(ov, conn, self.finish_socket_func)

    def write(self, conn: PipeHandle, buf: Buffer, offset: int = 0) -> Awaitable[int]:
        self._register_with_iocp(conn)
        ov = Overlapped(NULL)
        overlapped_ptr = ctypes.cast(ov.address, ctypes.POINTER(OVERLAPPED))
        overlapped_ptr.contents.Offset = offset & 0xFFFF_FFFF
        overlapped_ptr.contents.OffsetHigh = (offset >> 32) & 0xFFFF_FFFF

        ov.WriteFile(conn.fileno(), buf)

        return self._register(ov, conn, self.finish_socket_func)


class MyProactorEventLoop(asyncio.ProactorEventLoop):
    _proactor: MyIocpProactor

    def __init__(self, proactor: IocpProactor | None = None) -> None:
        if proactor is None:
            proactor = MyIocpProactor()
        super().__init__(proactor)

    async def file_open(self, path: str, mode: str = "rb") -> PipeHandle:
        if mode not in ("rb", "r+b"):
            raise ValueError(f"Unsupported mode: {mode}")

        return await self._proactor.connect_pipe(path)

    async def file_close(self, file: PipeHandle) -> None:
        file.close()

    async def file_write(self, file: PipeHandle, data: Buffer, offset: int = 0) -> int:
        return await self._proactor.write(file, data, offset)

    async def file_read(self, file: PipeHandle, n: int, offset: int = 0) -> bytes:
        buf = bytearray(n)
        transferred = await self._proactor.read_into(file, buf, offset)
        return buf[:transferred]

    async def file_readall(self, file: PipeHandle, chunk_size: int) -> AsyncIterator[bytes]:
        offset = 0
        buf = bytearray(chunk_size)
        read_into = self._proactor.read_into

        try:
            while True:
                transferred = await read_into(file, buf, offset)
                offset += transferred
                yield buf[:transferred]
        except OSError as e:
            if e.winerror != ERROR_HANDLE_EOF:
                raise


async def open(path: str, mode: str = "rb") -> AsyncFile:
    loop = asyncio.get_running_loop()
    assert isinstance(loop, MyProactorEventLoop)  # for mypy

    file = await loop.file_open(path)
    return AsyncFile(file, loop=loop)


async def readall(path: str, chunk_size: int) -> int:
    loop = asyncio.get_running_loop()
    assert isinstance(loop, MyProactorEventLoop)  # for mypy

    file = await loop.file_open(path)
    num_chunks = 0
    try:
        async for _data in loop.file_readall(file, chunk_size):
            num_chunks += 1
    finally:
        await loop.file_close(file)

    return num_chunks
