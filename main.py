from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import os

import csv
from datetime import datetime

def log_user_action(user_id, username, action, data):
    with open("user_log.csv", "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), user_id, username, action, data])

# Функция для подсчета количества пробных анализов по user_id
def get_trial_count(user_id):
    try:
        with open("user_log.csv", "r", encoding="utf-8") as f:
            return sum(
                int(row[1]) == int(user_id) and "Пробный анализ — ссылка" in row[3]
                for row in csv.reader(f)
            )
    except FileNotFoundError:
        return 0

from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Клавиатуры
start_keyboard = ReplyKeyboardMarkup([["Предоставить свои данные"]], resize_keyboard=True, one_time_keyboard=True)
menu_keyboard = ReplyKeyboardMarkup([["Пробный анализ"], ["Подписка на месяц"]], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать в Архиметрикс — умный ИИ-анализатор Telegram-каналов. Для начала работы подтвердите личность.\n\nНажмите кнопку ниже для подтверждения.",
        reply_markup=start_keyboard
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    username = update.message.from_user.username

    if text == "Предоставить свои данные":
        print(f"Верифицирован пользователь: ID={user_id}, username={username}")
        log_user_action(user_id, username, "Верификация", "")
        await update.message.reply_text(
            "✅ Спасибо! Вы верифицированы.\n\nТеперь вы можете воспользоваться пробным анализом или оформить подписку.",
            reply_markup=ReplyKeyboardRemove()
        )
        await update.message.reply_text("Выберите действие:", reply_markup=menu_keyboard)

    elif text == "Пробный анализ":
        await update.message.reply_text(
            "У вас осталось [5] из 5 пробных анализов.\n\nСкопируйте адрес канала в строку сообщения и нажмите «Отправить»."
        )
        log_user_action(user_id, username, "Пробный анализ", "")

    elif text == "Подписка на месяц":
        await update.message.reply_text(
            "💳 Для оформления подписки напишите /subscribe или воспользуйтесь меню (раздел в разработке)."
        )
        log_user_action(user_id, username, "Подписка на месяц", "")

    elif text.startswith("https://t.me/"):
        print(f"Пробный анализ для пользователя ID={user_id}, username={username}, ссылка={text}")
        log_user_action(user_id, username, "Пробный анализ — ссылка", text)
        await update.message.reply_text(
            "🟢 Принято! Ваш запрос на пробный анализ принят. В ближайшее время вы получите результат."
        )
    else:
        await update.message.reply_text("Не понимаю. Пожалуйста, используйте кнопки.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()