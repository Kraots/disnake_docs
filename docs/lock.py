import asyncio
from collections import defaultdict
from typing import Awaitable, Callable, Hashable, Union
from weakref import WeakValueDictionary

from .function import BoundArgs

__lock_dicts = defaultdict(WeakValueDictionary)

_IdCallableReturn = Union[Hashable, Awaitable[Hashable]]
_IdCallable = Callable[[BoundArgs], _IdCallableReturn]
ResourceId = Union[Hashable, _IdCallable]


class SharedEvent:
    """
    Context manager managing an internal event exposed through the wait coro.
    While any code is executing in this context manager, the underlying event will not be set;
    when all of the holders finish the event will be set.
    """

    def __init__(self):
        self._active_count = 0
        self._event = asyncio.Event()
        self._event.set()

    def __enter__(self):
        """Increment the count of the active holders and clear the internal event."""
        self._active_count += 1
        self._event.clear()

    def __exit__(self, _exc_type, _exc_val, _exc_tb):  # noqa: ANN001
        """Decrement the count of the active holders; if 0 is reached set the internal event."""
        self._active_count -= 1
        if not self._active_count:
            self._event.set()

    async def wait(self) -> None:
        """Wait for all active holders to exit."""
        await self._event.wait()
