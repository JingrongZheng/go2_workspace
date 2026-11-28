"""Small compatibility shim for the robot's Python 3.8."""
from contextlib import asynccontextmanager


@asynccontextmanager
async def aclosing(iterator):
    try:
        yield iterator
    finally:
        await iterator.aclose()
