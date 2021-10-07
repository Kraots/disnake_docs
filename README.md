[![Python versions](https://img.shields.io/pypi/pyversions/disnake.svg)](https://pypi.python.org/pypi/disnake-docs)

***

## About
***
This extension's purpose is of adding a "docs" command, its purpose is to help documenting in chat.

## How To Load It
***
```py
from disnake.ext import commands

bot = commands.Bot(...)
bot.load_extension('docs')

bot.run(...)
```

## How To Add More Items
***
To add more items besides `python` and `disnake`, you can subclass `doc.cog.Docs`
Example:
```py
from disnake.ext import commands
from docs import cog


class MyCog(cog.Docs):
    def __init__(self, bot):
        super().__init__(bot)
        # Now we set the new items
        # NOTE: It must be a list of tuples or a tuples of tuples
        self.items = (
            ('disnake', 'https://disnake.readthedocs.io/en/latest/'),
            ('python', 'https://docs.python.org/3/'),
            ('aiohttp', 'https://aiohttp.readthedocs.io/en/stable/'),
        )
        # NOTE: You must also add `disnake` and `python` manually, otherwise
        # it will only show the items you put.


bot = commands.Bot(...)
bot.add_cog(MyCog(bot))

bot.run(...)
```

## Inspired By
***
[python-discord/bot/bot/exts/info/doc](https://github.com/python-discord/bot/tree/main/bot/exts/info/doc) - The community bot for the Python Discord community