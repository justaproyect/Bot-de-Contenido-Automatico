import logging
import threading
from flask import Flask
from telegram.ext import ApplicationBuilder

from bot.config import TELEGRAM_BOT_TOKEN
from bot.handlers import get_conversation_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

health_app = Flask(__name__)


@health_app.route("/")
def health():
    return "Bot is running!"


def run_health():
    health_app.run(host="0.0.0.0", port=8080)


def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set. Check your .env file.")

    threading.Thread(target=run_health, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    conv_handler = get_conversation_handler()
    app.add_handler(conv_handler)

    logger.info("Bot started. Waiting for videos...")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
