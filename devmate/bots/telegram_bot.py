"""DevMate Telegram bot.  Run:  python telegram_bot.py

Commands:  /repo <github-url>   connect a repository for this chat
           /ask <question>      ask about code, errors or the connected repo
Any other text message is treated as a question.
"""
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from common import ask, link_repo, split_message


async def send(update: Update, text: str) -> None:
    for part in split_message(text, 3900):
        await update.message.reply_text(part, disable_web_page_preview=True)


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await send(update, "Hi, I'm DevMate 👋\nPaste an error or code, or connect a repo with /repo <github-url>.")


async def repo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await send(update, "Usage: /repo https://github.com/owner/project")
    await send(update, await link_repo("telegram", str(update.effective_chat.id), context.args[0]))


async def question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args) if context.args else (update.message.text or "")
    if not text.strip():
        return await send(update, "Usage: /ask <your question>")
    await update.effective_chat.send_action("typing")
    await send(update, await ask("telegram", str(update.effective_chat.id), text))


def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise SystemExit("Set TELEGRAM_TOKEN in .env first.")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("repo", repo))
    app.add_handler(CommandHandler("ask", question))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, question))
    app.run_polling()


if __name__ == "__main__":
    main()
