from flask import Flask
import os
import threading
from telegram.ext import Application, CommandHandler

TOKEN = os.environ.get("TELEGRAM_TOKEN")

# --- Функция бота ---
async def start(update, context):
    await update.message.reply_text("Бот работает! 🚀")

def run_bot():
    """Запускает бота в отдельном потоке"""
    app_bot = Application.builder().token(TOKEN).build()
    app_bot.add_handler(CommandHandler("start", start))
    print("✅ Бот запущен и ждёт команды...")
    app_bot.run_polling()

# --- Flask для Render ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот работает!"

@app.route('/health')
def health():
    return "OK"

if __name__ == "__main__":
    # Запускаем бота в фоновом потоке
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Запускаем Flask
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
