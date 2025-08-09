# File: parser_core/telegram_parser.py — логика получения данных из Telegram API (парсер каналов)

from __future__ import annotations
from typing import Dict, Any, List
import os
import json
from datetime import datetime

# Автозагрузка .env при импорте модуля
from pathlib import Path
from dotenv import load_dotenv

try:
    # Загружаем .env из корня проекта независимо от текущей рабочей директории
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)
except Exception as e:
    print(f"[telegram_parser] .env load failed: {e}")

# Пытаемся импортировать Telethon. Если не установлен — вернём аккуратную ошибку в meta.
try:
    from telethon import TelegramClient
    from telethon.tl.functions.channels import GetFullChannelRequest
    TELETHON_OK = True
except Exception as _e:
    TELETHON_OK = False
    _TELETHON_IMPORT_ERROR = str(_e)

SESSION_NAME = os.getenv("TELEGRAM_SESSION", "archimetrix_session")
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH") or ""


def _normalize_username(link_or_username: str) -> str:
    norm = (link_or_username or "").strip()
    if norm.startswith("https://t.me/"):
        norm = "@" + norm.split("https://t.me/")[1].strip("/")
    elif norm.startswith("t.me/"):
        norm = "@" + norm.split("t.me/")[1].strip("/")
    elif not norm.startswith("@"):
        norm = "@" + norm
    return norm


def _safe_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except Exception:
        return None


def _reactions_total(msg) -> int | None:
    try:
        if not getattr(msg, "reactions", None):
            return None
        # Telethon Message.reactions может быть None или объект с .results
        total = 0
        results = getattr(msg.reactions, "results", None)
        if results:
            for r in results:
                total += getattr(r, "count", 0) or 0
        return total
    except Exception:
        return None


def _message_to_dict(msg) -> Dict[str, Any]:
    return {
        "id": getattr(msg, "id", None),
        "date": getattr(getattr(msg, "date", None), "isoformat", lambda: None)(),
        "views": _safe_int(getattr(msg, "views", None)),
        "forwards": _safe_int(getattr(msg, "forwards", None)),
        "reactions_total": _reactions_total(msg),
        "is_forward": bool(getattr(msg, "fwd_from", None)),
        "reply_to": _safe_int(getattr(getattr(msg, "reply_to", None), "reply_to_msg_id", None)),
        "message": getattr(msg, "message", None),  # текст (может быть None для медиа)
        "media": bool(getattr(msg, "media", None)),
    }


def _collect_with_telethon(username: str, posts_limit: int = 30) -> Dict[str, Any]:
    if not TELETHON_OK:
        return {
            "channel": {"username": username},
            "stats": {},
            "time_series": {},
            "posts": [],
            "mentions": [],
            "forwards": [],
            "adposts": [],
            "meta": {
                "source": "telethon_core",
                "version": "0.2.0",
                "error": f"Telethon import failed: {_TELETHON_IMPORT_ERROR}",
            },
        }

    if not API_ID or not API_HASH:
        return {
            "channel": {"username": username},
            "stats": {},
            "time_series": {},
            "posts": [],
            "mentions": [],
            "forwards": [],
            "adposts": [],
            "meta": {
                "source": "telethon_core",
                "version": "0.2.0",
                "error": "API_ID/API_HASH not set in environment (.env)",
            },
        }

    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    async def run():
        # Получаем сущность канала
        entity = await client.get_entity(username)
        # Полная информация о канале (about, participants_count и пр.)
        full = await client(GetFullChannelRequest(channel=entity))
        ch = getattr(full, "chats", [None])[0] if getattr(full, "chats", None) else None
        full_chat = getattr(full, "full_chat", None)

        title = getattr(entity, "title", None) or getattr(ch, "title", None)
        about = getattr(full_chat, "about", None)
        participants = getattr(full_chat, "participants_count", None)

        # Последние N сообщений
        msgs = await client.get_messages(entity, limit=posts_limit)
        posts: List[Dict[str, Any]] = [_message_to_dict(m) for m in msgs]

        return {
            "channel": {
                "username": username,
                "title": title,
                "about": about,
                "avatar_url": None,  # можно добавить позже через download_profile_photo
                "category": None,
                "lang": None,
                "country": None,
                "subscribers": _safe_int(participants),  # может быть None для некоторых каналов
            },
            "stats": {
                # Базовые агрегаты по последним постам — прикинем медианы/средние позже
                "posts_count_sample": len(posts),
            },
            "time_series": {
                # Заполним позже, когда добавим периодические сборы
                "subscribers_daily": [],
                "err_series": [],
                "views_series": [],
            },
            "posts": posts,
            "mentions": [],
            "forwards": [],
            "adposts": [],
            "meta": {
                "source": "telethon_core",
                "version": "0.2.0",
            },
        }

    with client:
        return client.loop.run_until_complete(run())


def collect_channel_data(link_or_username: str) -> Dict[str, Any]:
    """
    Единая точка входа парсера: нормализует ввод и собирает данные из Telegram.
    Возвращает словарь в формате, совместимом с Архиметрикс.
    """
    if not link_or_username:
        raise ValueError("Укажи ссылку на канал или @username")

    username = _normalize_username(link_or_username)

    try:
        return _collect_with_telethon(username=username, posts_limit=30)
    except Exception as e:
        # Никогда не падаем на весь бот — возвращаем структуру с ошибкой в meta
        return {
            "channel": {"username": username},
            "stats": {},
            "time_series": {},
            "posts": [],
            "mentions": [],
            "forwards": [],
            "adposts": [],
            "meta": {
                "source": "telethon_core",
                "version": "0.2.0",
                "error": f"collect failed: {e}",
            },
        }