from flask import Flask
import os
from threading import Thread
from telegram.ext import Application, CommandHandler

# --- 1. Запуск ТВОЕГО бота (через polling) ---
TOKEN = os.environ.get("TELEGRAM_TOKEN") # Токен из переменных окружения

async def start(update, context):
    await update.message.reply_text("Бот работает!")

application = Application.builder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))

def run_bot():
    print("Бот запущен...")
    application.run_polling()

# --- 2. Веб-сервер Flask (для Render) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Бот запущен!"

@app.route('/health')
def health():
    return "OK"

if __name__ == "__main__":
    # Запускаем бота в фоновом потоке
    thread = Thread(target=run_bot)
    thread.start()
    # Запускаем Flask-сервер на порту, который выдал Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
