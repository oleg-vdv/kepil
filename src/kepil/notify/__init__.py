"""Уведомления оператору: подтверждения приходят в телефон, а не в браузер.

Модуль намеренно необязателен: если канал не настроен, система работает как
раньше — очередь подтверждений живёт в панели. Настроен — карточка действия
приходит в Telegram, и решение принимается оттуда.
"""

from __future__ import annotations

from typing import Any

from .telegram import Telegram, TelegramError, apply_press, parse_press, run

__all__ = ["Telegram", "TelegramError", "bot", "configured", "on_pending",
           "apply_press", "parse_press", "run"]


def configured() -> bool:
    from ..registry.store import settings
    org = settings()
    return bool(org.get("telegram_token") and org.get("telegram_chat_id"))


def bot() -> Telegram | None:
    """Готовый клиент или None, если канал не настроен."""
    from ..registry.store import settings
    org = settings()
    if not (org.get("telegram_token") and org.get("telegram_chat_id")):
        return None
    return Telegram(org["telegram_token"], org["telegram_chat_id"])


def on_pending(order: Any) -> None:
    """Заказ остановился на необратимом действии — зовём человека.

    Сбой канала не должен ломать заказ: задача уведомления — дотянуться до
    оператора, а не управлять работой. Если не дошло, карточка всё равно ждёт
    в панели.
    """
    client = bot()
    if client is None or not order.pending:
        return
    from ..professions import Profession
    rollback = Profession(order.definition()).rollback(order.pending["action"])
    try:
        client.ask_confirmation(order, order.pending, rollback)
    except TelegramError:
        pass
