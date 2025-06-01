import unittest
import asyncio

from async_file import async_file

class MyIsolatedAsyncioTestCase(unittest.IsolatedAsyncioTestCase):
    def _setupAsyncioRunner(self):
        assert self._asyncioRunner is None, 'asyncio runner is already initialized'
        runner = asyncio.Runner(debug=True, loop_factory=async_file.MyProactorEventLoop)
        self._asyncioRunner = runner


class AsyncFileTest(MyIsolatedAsyncioTestCase):
    
    async def test_read_write(self):
        path = "async-file-test.txt"

        async with await async_file.open(path) as fp:
            assert await fp.write(b"asd") == 3
            assert await fp.write(b"qwe") == 3
            assert fp.seek(0) == 0
            assert await fp.read(3) == b"asd"
            assert await fp.read(3) == b"qwe"
            assert isinstance(fp.fileno(), int)
            assert not fp.closed
        assert fp.closed
