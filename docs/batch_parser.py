from __future__ import annotations

import asyncio
import collections
from collections import defaultdict
from contextlib import suppress
from operator import attrgetter
from typing import Deque, Dict, List, NamedTuple, Optional, Union

from bs4 import BeautifulSoup
import aiohttp

from .utils import create_task
from . import cog, doc_cache
from .parsing import get_symbol_markdown


class QueueItem(NamedTuple):
    """Contains a `DocItem` and the `BeautifulSoup` object needed to parse it."""

    doc_item: cog.DocItem
    soup: BeautifulSoup

    def __eq__(self, other: Union[QueueItem, cog.DocItem]):
        if isinstance(other, cog.DocItem):
            return self.doc_item == other
        return NamedTuple.__eq__(self, other)


class ParseResultFuture(asyncio.Future):
    """
    Future with metadata for the parser class.
    `user_requested` is set by the parser when a Future is requested by an user and moved to the front,
    allowing the futures to only be waited for when clearing if they were user requested.
    """

    def __init__(self):
        super().__init__()
        self.user_requested = False


class BatchParser:
    """
    DocItems are added through the `add_item` method which adds them to the `_page_doc_items` dict.
    `get_markdown` is used to fetch the Markdown; when this is used for the first time on a page,
    all of the symbols are queued to be parsed to avoid multiple web requests to the same page.
    """

    def __init__(self):
        self._queue: Deque[QueueItem] = collections.deque()
        self._page_doc_items: Dict[str, List[cog.DocItem]] = defaultdict(list)
        self._item_futures: Dict[cog.DocItem, ParseResultFuture] = defaultdict(ParseResultFuture)
        self._parse_task = None
        self._loop = asyncio.get_event_loop()

    async def get_markdown(self, doc_item: cog.DocItem) -> Optional[str]:
        """
        Get the result Markdown of `doc_item`.
        If no symbols were fetched from `doc_item`s page before,
        the HTML has to be fetched and then all items from the page are put into the parse queue.
        Not safe to run while `self.clear` is running.
        """
        if doc_item not in self._item_futures and doc_item not in self._queue:
            self._item_futures[doc_item].user_requested = True

            async with aiohttp.ClientSession() as session:
                async with session.get(doc_item.url) as response:
                    soup = await self._loop.run_in_executor(
                        None,
                        BeautifulSoup,
                        await response.text(encoding="utf8"),
                        'html.parser'
                    )

            self._queue.extendleft(QueueItem(item, soup) for item in self._page_doc_items[doc_item.url])

            if self._parse_task is None:
                self._parse_task = create_task(self._parse_queue(), name="Queue parse")
        else:
            self._item_futures[doc_item].user_requested = True
        with suppress(ValueError):
            # If the item is not in the queue then the item is already parsed or is being parsed
            self._move_to_front(doc_item)
        return await self._item_futures[doc_item]

    async def _parse_queue(self) -> None:
        """
        The coroutine will run as long as the queue is not empty, resetting `self._parse_task` to None when finished.
        """
        try:
            while self._queue:
                item, soup = self._queue.pop()
                markdown = None

                if (future := self._item_futures[item]).done():
                    # Some items are present in the inventories multiple times under different symbol names,
                    # if we already parsed an equal item, we can just skip it.
                    continue

                try:
                    markdown = await self._loop.run_in_executor(None, get_symbol_markdown, soup, item)
                    if markdown is not None:
                        doc_cache.set(item, markdown)
                except Exception:
                    pass

                future.set_result(markdown)
                del self._item_futures[item]
                await asyncio.sleep(0.1)
        finally:
            self._parse_task = None

    def _move_to_front(self, item: Union[QueueItem, cog.DocItem]) -> None:
        """Move `item` to the front of the parse queue."""
        # The parse queue stores soups along with the doc symbols in QueueItem objects,
        # in case we're moving a DocItem we have to get the associated QueueItem first and then move it.
        item_index = self._queue.index(item)
        queue_item = self._queue[item_index]
        del self._queue[item_index]

        self._queue.append(queue_item)

    def add_item(self, doc_item: cog.DocItem) -> None:
        """Map a DocItem to its page so that the symbol will be parsed once the page is requested."""
        self._page_doc_items[doc_item.url].append(doc_item)

    async def clear(self) -> None:
        """
        Clear all internal symbol data.
        Wait for all user-requested symbols to be parsed before clearing the parser.
        """
        for future in filter(attrgetter("user_requested"), self._item_futures.values()):
            await future
        if self._parse_task is not None:
            self._parse_task.cancel()
        self._queue.clear()
        self._page_doc_items.clear()
        self._item_futures.clear()
