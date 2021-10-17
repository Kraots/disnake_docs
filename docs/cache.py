from __future__ import annotations

from typing import Optional, Union, Dict, TYPE_CHECKING
if TYPE_CHECKING:
    from .cog import DocItem


class DocCache:
    def __init__(self) -> None:
        self.cache = {}

    def set(self, item: DocItem, value: str) -> None:
        """
        Set the Markdown `value` for the symbol `item`.
        All keys from a single page are stored together.
        """
        cache = self.cache.get(item.package)
        if cache is None:
            self.cache[item.package] = {}
        self.cache[item.package][item.symbol_id] = value

    def get(self, item: DocItem) -> Optional[str]:
        """Return the Markdown content of the symbol `item` if it exists."""

        key: Union[Dict, None] = self.cache.get(item.package)
        if key is not None:
            result = key.get(item.symbol_id)
            return result
        return None

    def delete(self, package: str = None) -> bool:
        """Remove all values for `package`; return True if at least one key was deleted, False otherwise."""

        if package:
            try:
                self.cache.pop(package)
                return True
            except KeyError:
                return False
        self.cache = {}
