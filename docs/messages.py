import random

import disnake
from disnake import AppCmdInter

NEGATIVE_REPLIES = (
    "Noooooo!!",
    "Nope.",
    "I'm sorry Dave, I'm afraid I can't do that.",
    "I don't think so.",
    "Not gonna happen.",
    "Out of the question.",
    "Huh? No.",
    "Nah.",
    "Naw.",
    "Not likely.",
    "No way, José.",
    "Not in a million years.",
    "Fat chance.",
    "Certainly not.",
    "NEGATORY.",
    "Nuh-uh.",
    "Not in my house!"
)


async def send_denial(
    inter: AppCmdInter,
    reason: str,
    *,
    view: disnake.ui.View = None,
    ephemeral: bool = False
) -> None:
    """Send an embed denying the user with the given reason."""
    embed = disnake.Embed()
    embed.colour = disnake.Colour.red()
    embed.title = random.choice(NEGATIVE_REPLIES)
    embed.description = reason

    return await inter.send(embed=embed, view=view, ephemeral=ephemeral)
