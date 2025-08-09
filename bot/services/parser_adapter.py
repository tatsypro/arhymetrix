# File: bot/services/parser_adapter.py — адаптер для вызова парсера из бота

from __future__ import annotations
from typing import Dict
from parser_core import collect_channel_data


def fetch_channel_summary(link_or_username: str) -> Dict:
    """
    Тонкий адаптер между ботом и парсером.
    Бот вызывает ЭТУ функцию, внутри она обращается к parser_core.
    Позже мы сможем заменить реализацию (добавить Telethon/скрейп) без изменений в боте.
    """
    return collect_channel_data(link_or_username)
