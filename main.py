# File: main.py — основной бот Архиметрикс (логика Telegram-бота)

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import os
import requests
import json
import re
from bot.services.parser_adapter import fetch_channel_summary

with open("Arhy_prompt_main.txt", encoding="utf-8") as f:
    BASE_PROMPT = f.read()

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

# Функция для сбора данных TGStat
def collect_tgstat_data(channel_link):
    """
    Собирает все необходимые данные TGStat для промпта.
    """
    channel = channel_link.replace("https://t.me/", "").strip("/")
    print("TGStat channelId:", channel)
    base_url = "https://api.tgstat.ru"
    token = TGSTAT_TOKEN

    def get(endpoint, **kwargs):
        url = f"{base_url}/{endpoint}"
        params = {"token": token, "channelId": channel}
        params.update(kwargs)
        try:
            resp = requests.get(url, params=params, timeout=10)
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    data = {}

    # 1. channels/get
    data["get"] = get("channels/get")

    # 2. channels/stat
    data["stat"] = get("channels/stat")

    # 3. channels/subscribers
    data["subscribers"] = get("channels/subscribers", period="month")  # динамика за месяц

    # 4. channels/views
    data["views"] = get("channels/views", period="month")

    # 5. channels/err
    data["err"] = get("channels/err", period="month")

    # 6. channels/mentions
    data["mentions"] = get("channels/mentions", limit=10)  # последние 10 упоминаний

    # 7. channels/forwards
    data["forwards"] = get("channels/forwards", limit=10)  # последние 10 форвардов

    # 8. channels/posts
    posts_resp = get("channels/posts", limit=5)  # последние 5 постов
    data["posts"] = posts_resp

    # 9. posts/stat для каждого поста (если есть посты)
    if posts_resp.get("ok") and posts_resp.get("result"):
        data["posts_stat"] = []
        for post in posts_resp["result"]:
            post_id = post.get("id")
            if post_id:
                stat = get("posts/stat", postId=post_id)
                data["posts_stat"].append({"post_id": post_id, "stat": stat})
    else:
        data["posts_stat"] = []

    # 10. channels/adposts (реклама)
    data["adposts"] = get("channels/adposts", limit=5)

    print("TGStat ответ:", json.dumps(data, ensure_ascii=False, indent=2))
    return data

from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
TGSTAT_TOKEN = os.getenv("TGSTAT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# OpenAI integration
import openai

def ask_chatgpt(analysis_json: str):
    """
    Отправляет единый промпт: BASE_PROMPT + объединённые данные канала
    (parser_core + tgstat), переданные строкой JSON.
    """
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    full_prompt = BASE_PROMPT + "\n\nДанные канала (parser_core + TGStat, если доступен):\n" + analysis_json
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Ты — эксперт по анализу Telegram-каналов."},
            {"role": "user", "content": full_prompt}
        ],
        max_tokens=1000,
        temperature=0.1,
    )
    return response.choices[0].message.content.strip()

def format_gpt_reply(gpt_json_str):
    try:
        data = json.loads(gpt_json_str)
        color = data.get("traffic_light", {}).get("color", "")
        color_emoji = {
            "green": "🟢",
            "yellow": "🟡",
            "red": "🔴"
        }.get(color, "⚪️")
        color_text = {
            "green": "Зелёный (можно давать рекламу)",
            "yellow": "Жёлтый (возможна реклама, нужен дополнительный анализ)",
            "red": "Красный (реклама не рекомендуется)"
        }.get(color, f"({color})")
        rec = data.get("traffic_light", {}).get("recommendation", "")

        fakes = data.get("fakes_estimate", {})
        fake_pct = fakes.get("fake_probability_percent")
        real_pct = fakes.get("real_users_percent")
        explanation = fakes.get("explanation", "")

        recommendations = data.get("short_recommendations", [])
        if isinstance(recommendations, list):
            recs_text = "\n".join(f"— {x}" for x in recommendations if x)
        else:
            recs_text = ""

        out = f"{color_emoji} Светофор: {color_text}\n"
        if fake_pct is not None and real_pct is not None:
            out += f"Вероятность накрутки: {fake_pct}%\nПримерно {real_pct}% реальных пользователей\n"
        if explanation:
            out += f"{explanation}\n"
        if recs_text:
            out += "\nОсновные метрики, по которым сделаны выводы:\n" + recs_text
        return out.strip()
    except Exception as e:
        return f"Ошибка форматирования ответа: {e}\n{gpt_json_str}"

# Клавиатуры
start_keyboard = ReplyKeyboardMarkup([["Предоставить свои данные"]], resize_keyboard=True, one_time_keyboard=True)
menu_keyboard = ReplyKeyboardMarkup([["Пробный анализ"], ["Подписка на месяц"]], resize_keyboard=True)
back_keyboard = ReplyKeyboardMarkup([["Назад"]], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    print("user_id для проверки верификации:", user_id)
    already_verified = False
    try:
        with open("user_log.csv", "r", encoding="utf-8") as f:
            for row in csv.reader(f):
                print("Проверяем строку:", row)
                if int(row[1]) == int(user_id) and "Верификация" in row[3]:
                    already_verified = True
                    break
    except FileNotFoundError:
        pass

    if already_verified:
        await update.message.reply_text(
            "Рад снова вас видеть!\nВыберите действие:",
            reply_markup=menu_keyboard
        )
    else:
        await update.message.reply_text(
            "Добро пожаловать в Архиметрикс — умный ИИ-анализатор Telegram-каналов. Для начала работы подтвердите личность.\n\nНажмите кнопку ниже для подтверждения.",
            reply_markup=start_keyboard
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id
    username = update.message.from_user.username

    # Проверяем, был ли пользователь уже верифицирован
    already_verified = False
    try:
        with open("user_log.csv", "r", encoding="utf-8") as f:
            for row in csv.reader(f):
                print("Проверяем строку:", row)
                if int(row[1]) == int(user_id) and "Верификация" in row[3]:
                    already_verified = True
                    break
    except FileNotFoundError:
        pass

    if text == "Предоставить свои данные" and not already_verified:
        print(f"Верифицирован пользователь: ID={user_id}, username={username}")
        log_user_action(user_id, username, "Верификация", "")
        await update.message.reply_text(
            "✅ Спасибо! Вы верифицированы.\n\nТеперь вы можете воспользоваться пробным анализом или оформить подписку.",
            reply_markup=ReplyKeyboardRemove()
        )
        await update.message.reply_text("Выберите действие:", reply_markup=menu_keyboard)
    elif text == "Предоставить свои данные" and already_verified:
        await update.message.reply_text("Вы уже верифицированы!\n\nВыберите действие:", reply_markup=menu_keyboard)

    elif text == "Пробный анализ":
        max_trials = 5
        used_trials = get_trial_count(user_id)
        left = max_trials - used_trials
        await update.message.reply_text(
            f"У вас осталось [{left}] из {max_trials} пробных анализов.\n\nСкопируйте адрес канала в строку сообщения и нажмите «Отправить».",
            reply_markup=back_keyboard
        )
        log_user_action(user_id, username, "Пробный анализ", "")

    elif text == "Подписка на месяц":
        await update.message.reply_text(
            "💳 Для оформления подписки напишите /subscribe или воспользуйтесь меню (раздел в разработке)."
        )
        log_user_action(user_id, username, "Подписка на месяц", "")

    elif text == "Назад":
        await update.message.reply_text("Выберите действие:", reply_markup=menu_keyboard)

    elif re.search(r"(https?://)?t\.me/[A-Za-z0-9_]+", text):
        print(f"Пробный анализ для пользователя ID={user_id}, username={username}, ссылка={text}")
        log_user_action(user_id, username, "Пробный анализ — ссылка", text)
        await update.message.reply_text("🟢 Принято! Ваш запрос на пробный анализ принят. Выполняется анализ…")

        try:
            # 1) Сбор из parser_core (ядро на Telegram API)
            parser_data = fetch_channel_summary(text)

            # 2) TGStat как дополнительный источник (если токен задан)
            tgstat_data = {}
            if TGSTAT_TOKEN:
                try:
                    tgstat_data = collect_tgstat_data(text)
                except Exception as e:
                    tgstat_data = {"error": f"TGStat failed: {e}"}
            else:
                tgstat_data = {"skipped": "TGSTAT_TOKEN not set"}

            # 3) Объединяем и отправляем в ИИ
            analysis_payload = {
                "parser_core": parser_data,
                "tgstat": tgstat_data,
            }
            analysis_json = json.dumps(analysis_payload, ensure_ascii=False, indent=2)

            gpt_reply = ask_chatgpt(analysis_json)
            formatted_reply = format_gpt_reply(gpt_reply)
            await update.message.reply_text(formatted_reply)
            await update.message.reply_text("Выберите действие:", reply_markup=menu_keyboard)
        except Exception as e:
            await update.message.reply_text(f"Ошибка при анализе: {e}")
    else:
        await update.message.reply_text("Не понимаю. Пожалуйста, используйте кнопки.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()