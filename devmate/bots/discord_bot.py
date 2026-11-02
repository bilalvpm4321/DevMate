"""DevMate Discord bot.  Run:  python discord_bot.py

Commands:  !repo <github-url>   connect a repository for this server
           !ask <question>      ask about code, errors or the connected repo
The bot also answers when mentioned, and auto-replies to pasted error messages.
"""
import os

import discord
from discord.ext import commands

from common import ask, link_repo, looks_like_error, split_message

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


async def reply(message: discord.Message, question: str) -> None:
    community = str(message.guild.id if message.guild else message.author.id)
    async with message.channel.typing():
        answer = await ask("discord", community, question)
    for part in split_message(answer, 1900):
        await message.reply(part, mention_author=False)


@bot.event
async def on_ready():
    print(f"DevMate is online as {bot.user}")


@bot.command(name="repo")
async def repo_cmd(ctx: commands.Context, url: str):
    async with ctx.typing():
        await ctx.reply(await link_repo("discord", str(ctx.guild.id if ctx.guild else ctx.author.id), url))


@bot.command(name="ask")
async def ask_cmd(ctx: commands.Context, *, question: str):
    await reply(ctx.message, question)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    await bot.process_commands(message)
    if message.content.startswith("!"):
        return
    text = message.content.replace(f"<@{bot.user.id}>", "").strip()
    if bot.user in message.mentions and text:
        await reply(message, text)
    elif looks_like_error(message.content):
        await reply(message, message.content)


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Set DISCORD_TOKEN in .env first.")
    bot.run(token)
