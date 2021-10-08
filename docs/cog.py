from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Dict, NamedTuple, Optional, List, Union

import aiohttp
import disnake
from disnake import Client
from disnake.ext import commands
from disnake.ext.commands import Bot

from .converters import Inventory, PackageName, ValidURL
from .lock import SharedEvent, lock
from .messages import send_denial
from .pagination import EmbedPaginator, Paginator
from . import NAMESPACE, PRIORITY_PACKAGES, batch_parser, doc_cache
from .inventory_parser import InventoryDict, fetch_inventory
from .utils import (
    create_task,
    Scheduler,
    finder,
    QuitButton
)

# symbols with a group contained here will get the group prefixed on duplicates
FORCE_PREFIX_GROUPS = (
    "term",
    "label",
    "token",
    "doc",
    "pdbcommand",
    "2to3fixer",
)
NOT_FOUND_DELETE_DELAY = 30.0
# Delay to wait before trying to reach a rescheduled inventory again, in minutes
FETCH_RESCHEDULE_DELAY = SimpleNamespace(first=2, repeated=5)

COMMAND_LOCK_SINGLETON = "inventory refresh"


class DocItem(NamedTuple):
    """Holds inventory symbol information."""

    package: str  # Name of the package name the symbol is from
    group: str  # Interpshinx "role" of the symbol, for example `label` or `method`
    base_url: str  # Absolute path to to which the relative path resolves, same for all items with the same package
    relative_url_path: str  # Relative path to the page where the symbol is located
    symbol_id: str  # Fragment id used to locate the symbol on the page

    @property
    def url(self) -> str:
        """Return the absolute url to the symbol."""
        return self.base_url + self.relative_url_path


class Docs(commands.Cog):
    """A set of commands for querying & displaying documentation."""

    def __init__(self, bot: Union[Client, Bot], *, limit: int = 4):
        """
        If limit is given, the max amount of entries to look up for will become that limit.

        It's recommended that this never goes above **8**, otherwise expect slow results.

        Default is 4.
        """

        # Contains URLs to documentation home pages.
        # Used to calculate inventory diffs on refreshes and to display all currently stored inventories.
        self.base_urls = {}
        self.bot = bot
        self.limit = limit
        self.doc_symbols: Dict[str, DocItem] = {}  # Maps symbol names to objects containing their metadata.
        self.item_fetcher = batch_parser.BatchParser()

        self.inventory_scheduler = Scheduler(self.__class__.__name__)

        self.refresh_event = asyncio.Event()
        self.refresh_event.set()
        self.symbol_get_event = SharedEvent()
        self.items = (
            ('python', 'https://docs.python.org/3/'),
            ('disnake', 'https://disnake.readthedocs.io/en/latest/')
        )
        self.init_refresh_task = create_task(
            self.init_refresh_inventory(),
            name="Doc inventory init",
            event_loop=self.bot.loop
        )

    @lock(NAMESPACE, COMMAND_LOCK_SINGLETON, raise_error=True)
    async def init_refresh_inventory(self) -> None:
        """Refresh documentation inventory on cog initialization."""
        await self.refresh_inventories()

    def update_single(self, package_name: str, base_url: str, inventory: InventoryDict) -> None:
        """
        Build the inventory for a single package and adds its items to the cache.
        Where:
            * `package_name` is the package name to use in logs and when qualifying symbols
            * `base_url` is the root documentation URL for the specified package, used to build
                absolute paths that link to specific symbols
            * `package` is the content of a intersphinx inventory.
        """
        self.base_urls[package_name] = base_url

        for group, items in inventory.items():
            for symbol_name, relative_doc_url in items:

                # e.g. get 'class' from 'py:class'
                group_name = group.split(":")[1]
                symbol_name = self.ensure_unique_symbol_name(
                    package_name,
                    group_name,
                    symbol_name,
                )

                relative_url_path, _, symbol_id = relative_doc_url.partition("#")
                # Intern fields that have shared content so we're not storing unique strings for every object
                doc_item = DocItem(
                    package_name,
                    sys.intern(group_name),
                    base_url,
                    sys.intern(relative_url_path),
                    symbol_id,
                )
                self.doc_symbols[symbol_name] = doc_item
                self.item_fetcher.add_item(doc_item)

    async def update_or_reschedule_inventory(
        self,
        api_package_name: str,
        base_url: str,
        inventory_url: str,
    ) -> None:
        """
        Update the cog's inventories, or reschedule this method to execute again if the remote inventory is unreachable.
        The first attempt is rescheduled to execute in `FETCH_RESCHEDULE_DELAY.first` minutes, the subsequent attempts
        in `FETCH_RESCHEDULE_DELAY.repeated` minutes.
        """
        package = await fetch_inventory(inventory_url)

        if not package:
            if api_package_name in self.inventory_scheduler:
                self.inventory_scheduler.cancel(api_package_name)
                delay = FETCH_RESCHEDULE_DELAY.repeated
            else:
                delay = FETCH_RESCHEDULE_DELAY.first
            self.inventory_scheduler.schedule_later(
                delay * 60,
                api_package_name,
                self.update_or_reschedule_inventory(api_package_name, base_url, inventory_url),
            )
        else:
            if not base_url:
                base_url = self.base_url_from_inventory_url(inventory_url)
            self.update_single(api_package_name, base_url, package)

    def ensure_unique_symbol_name(self, package_name: str, group_name: str, symbol_name: str) -> str:
        """
        Ensure `symbol_name` doesn't overwrite an another symbol in `doc_symbols`.
        For conflicts, rename either the current symbol or the existing symbol with which it conflicts.
        Store the new name in `renamed_symbols` and return the name to use for the symbol.
        If the existing symbol was renamed or there was no conflict, the returned name is equivalent to `symbol_name`.
        """
        if (item := self.doc_symbols.get(symbol_name)) is None:
            return symbol_name  # There's no conflict so it's fine to simply use the given symbol name.

        def rename(prefix: str, *, rename_extant: bool = False) -> str:
            new_name = f"{prefix}.{symbol_name}"
            if new_name in self.doc_symbols:
                # If there's still a conflict, qualify the name further.
                if rename_extant:
                    new_name = f"{item.package}.{item.group}.{symbol_name}"
                else:
                    new_name = f"{package_name}.{group_name}.{symbol_name}"

            if rename_extant:
                # Instead of renaming the current symbol, rename the symbol with which it conflicts.
                self.doc_symbols[new_name] = self.doc_symbols[symbol_name]
                return symbol_name
            else:
                return new_name

        # When there's a conflict, and the package names of the items differ, use the package name as a prefix.
        if package_name != item.package:
            if package_name in PRIORITY_PACKAGES:
                return rename(item.package, rename_extant=True)
            else:
                return rename(package_name)

        # If the symbol's group is a non-priority group from FORCE_PREFIX_GROUPS,
        # add it as a prefix to disambiguate the symbols.
        elif group_name in FORCE_PREFIX_GROUPS:
            if item.group in FORCE_PREFIX_GROUPS:
                needs_moving = FORCE_PREFIX_GROUPS.index(group_name) < FORCE_PREFIX_GROUPS.index(item.group)
            else:
                needs_moving = False
            return rename(item.group if needs_moving else group_name, rename_extant=needs_moving)

        # If the above conditions didn't pass, either the existing symbol has its group in FORCE_PREFIX_GROUPS,
        # or deciding which item to rename would be arbitrary, so we rename the existing symbol.
        else:
            return rename(item.group, rename_extant=True)

    async def refresh_inventories(self) -> None:
        """Refresh internal documentation inventories."""
        self.refresh_event.clear()
        await self.symbol_get_event.wait()
        self.inventory_scheduler.cancel_all()

        self.base_urls.clear()
        self.doc_symbols.clear()
        await self.item_fetcher.clear()

        coros = [
            self.update_or_reschedule_inventory(
                item[0], item[1], item[1] + 'objects.inv'
            ) for item in self.items
        ]
        asyncio.gather(*coros)

        self.refresh_event.set()

    def get_symbol_item(self, symbol_name: str) -> List[str, Optional[DocItem]]:
        """
        Get the `DocItem` and the symbol name used to fetch it from the `doc_symbols` dict.
        """
        doc_symbols = list(self.doc_symbols.items())
        matches = finder(symbol_name, doc_symbols, key=lambda t: t[0], lazy=False)[:self.limit]
        return matches

    async def get_symbol_markdown(self, doc_item: DocItem) -> str:
        """
        Get the Markdown from the symbol `doc_item` refers to.
        `item_fetcher` is used to fetch the page and parse the
        HTML from it into Markdown.
        """
        markdown = doc_cache.get(doc_item)
        if markdown is None:
            try:
                markdown = await self.item_fetcher.get_markdown(doc_item)

            except aiohttp.ClientError:
                return "Unable to parse the requested symbol due to a network error."

            except Exception:
                return "Unable to parse the requested symbol due to an error."

            if markdown is None:
                return "Unable to parse the requested symbol."

        return markdown

    async def create_symbol_embed(self, symbol_name: str) -> Optional[List[disnake.Embed]]:
        """
        Attempt to scrape and fetch the data for the given `symbol_name`, and build an embed from its contents.
        If the symbol is known, an Embed with documentation about it is returned.
        """
        if not self.refresh_event.is_set():
            await self.refresh_event.wait()
        # Ensure a refresh can't run in case of a context switch until the with block is exited
        with self.symbol_get_event:
            data = self.get_symbol_item(symbol_name)
            if len(data) == 0:
                return None
            embeds = []
            for i in data:
                symbol_name, doc_item = i

                embed = disnake.Embed(
                    title=disnake.utils.escape_markdown(symbol_name),
                    url=f"{doc_item.url}#{doc_item.symbol_id}",
                    description=await self.get_symbol_markdown(doc_item)
                )
                embeds.append(embed)
            return embeds

    @commands.group(name="docs", aliases=("doc", "d"), invoke_without_command=True)
    async def docs_group(self, ctx: commands.Context, *, symbol_name: Optional[str]) -> None:
        """Look up documentation for Python symbols."""
        await self.get_command(ctx, symbol_name=symbol_name)

    @docs_group.command(name="getdoc", aliases=("g",))
    async def get_command(self, ctx: commands.Context, *, symbol_name: Optional[str]) -> None:
        """
        Return a documentation embed for a given symbol.
        If no symbol is given, return a list of all available inventories.
        Examples:
            !docs
            !docs aiohttp
            !docs aiohttp.ClientSession
            !docs getdoc aiohttp.ClientSession
        """

        if not symbol_name:
            lines = sorted(f"• [`{name}`]({url})" for name, url in self.base_urls.items())
            if self.base_urls:
                paginator = Paginator(
                    ctx,
                    lines,
                    per_page=5,
                    title=f'All inventories (`{len(self.base_urls)}` total)'
                )
                await paginator.start()

            else:
                inventory_embed = disnake.Embed(title=f'All inventories (`{len(self.base_urls)}` total)', color=disnake.Color.blurple())
                inventory_embed.description = "Hmmm, seems like there's nothing here yet."
                await ctx.send(embed=inventory_embed)

        else:
            symbol = symbol_name.strip("`")
            async with ctx.typing():
                doc_embeds = await self.create_symbol_embed(symbol)

            if doc_embeds is None:
                view = QuitButton(ctx, timeout=NOT_FOUND_DELETE_DELAY, delete_after=True)
                view.message = await send_denial(ctx, "No documentation found for the requested symbol.", view=view)

            else:
                if len(doc_embeds) == 1:
                    view = QuitButton(ctx)
                    view.message = await ctx.send(embed=doc_embeds[0], view=view)
                    return

                paginator = EmbedPaginator(ctx, doc_embeds)
                await paginator.start()

    @staticmethod
    def base_url_from_inventory_url(inventory_url: str) -> str:
        """Get a base url from the url to an objects inventory by removing the last path segment."""
        return inventory_url.removesuffix("/").rsplit("/", maxsplit=1)[0] + "/"

    @docs_group.command(name="setdoc", aliases=("s",))
    @commands.is_owner()
    @lock(NAMESPACE, COMMAND_LOCK_SINGLETON, raise_error=True)
    async def set_command(
        self,
        ctx: commands.Context,
        package_name: PackageName,
        inventory: Inventory,
        base_url: ValidURL = "",
    ) -> None:
        """
        Adds a new documentation metadata object to the inventory.
        If the base url is not specified, a default created by removing the last segment of the inventory url is used.
        Example:
            !docs setdoc \
                    python \
                    https://docs.python.org/3/objects.inv
        """
        if base_url and not base_url.endswith("/"):
            raise commands.BadArgument("The base url must end with a slash.")
        inventory_url, inventory_dict = inventory

        if not base_url:
            base_url = self.base_url_from_inventory_url(inventory_url)

        self.update_single(package_name, base_url, inventory_dict)
        await ctx.send(f"Added the package `{package_name}` the inventories.")

    @docs_group.command(name="refreshdoc", aliases=("refresh", "r"))
    @commands.is_owner()
    @lock(NAMESPACE, COMMAND_LOCK_SINGLETON, raise_error=True)
    async def refresh_command(self, ctx: commands.Context) -> None:
        """Refresh inventories and show the difference."""
        old_inventories = set(self.base_urls)
        with ctx.typing():
            await self.refresh_inventories()
        new_inventories = set(self.base_urls)

        if added := ", ".join(new_inventories - old_inventories):
            added = "+ " + added

        if removed := ", ".join(old_inventories - new_inventories):
            removed = "- " + removed

        embed = disnake.Embed(
            title="Inventories refreshed",
            description=f"```diff\n{added}\n{removed}```" if added or removed else ""
        )
        await ctx.send(embed=embed)

    @docs_group.command(name="cleardoccache", aliases=("deletedoccache", "c",))
    @commands.is_owner()
    async def clear_cache_command(
        self,
        ctx: commands.Context
    ) -> None:
        """Clears the cache while refreshing the inventories like `!docs refreshdoc` does."""

        doc_cache.delete()
        await self.refresh_inventories()
        await ctx.send("Successfully cleared the cache and refreshed the inventories.")

    def cog_unload(self) -> None:
        """Clear scheduled inventories, queued symbols and cleanup task on cog unload."""
        self.inventory_scheduler.cancel_all()
        self.init_refresh_task.cancel()
        create_task(self.item_fetcher.clear(), name="Docs.item_fetcher unload clear")
