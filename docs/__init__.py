from typing import Union

from disnake import Client
from disnake.ext.commands import Bot

__version__ = '1.0.10'

MAX_SIGNATURE_AMOUNT = 3
PRIORITY_PACKAGES = (
    "python",
)
NAMESPACE = "doc"


def setup(bot: Union[Client, Bot]) -> None:
    """Load the Doc cog."""
    from .cog import Docs
    bot.add_cog(Docs(bot))
