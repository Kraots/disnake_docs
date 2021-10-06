[![Python versions](https://img.shields.io/pypi/pyversions/disnake.svg)](https://pypi.python.org/pypi/disnake-docs)
[![License](https://img.shields.io/pypi/l/jishaku.svg)](https://github.com/Kraots/disnake_docs/blob/master/LICENSE)

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

## Inspired By
***
[python-discord/bot](https://github.com/python-discord/bot) - The community bot for the Python Discord community