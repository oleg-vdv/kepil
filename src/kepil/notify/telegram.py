"""Подтверждения в телефон.

Оператор не должен сидеть за ноутбуком: карточка действия приходит в Telegram
с двумя кнопками, и решение принимается там же — в дороге, в очереди, где
угодно. Панель нужна раз в неделю, чтобы посмотреть цифры и поправить
настройки.

Telegram выбран потому, что бот заводится за пять минут, ничего не стоит и не
требует ни верификации бизнеса, ни посредников. WhatsApp нужен для общения с
клиентами заказчика — это другая задача и другой канал.

Стандартная библиотека: обращения к API идут через urllib, транспорт можно
подменить для тестов.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 30


class TelegramError(RuntimeError):
    """Ответ Telegram с ошибкой или недоступный API."""


def _http(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT + 5) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise TelegramError(f"Telegram вернул {exc.code}: {exc.reason}") from None
    except OSError as exc:
        raise TelegramError(f"нет связи с Telegram: {exc}") from None


class Telegram:
    """Тонкий клиент: отправка карточки подтверждения и разбор нажатий."""

    def __init__(self, token: str, chat_id: str,
                 transport: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None):
        self.token = token
        self.chat_id = str(chat_id)
        self._transport = transport or _http

    # --- низкий уровень ---

    def call(self, method: str, **payload: Any) -> dict[str, Any]:
        result = self._transport(API.format(token=self.token, method=method), payload)
        if not result.get("ok", False):
            raise TelegramError(result.get("description", "неизвестная ошибка"))
        return result.get("result", {})

    # --- то, что нужно оператору ---

    def check(self) -> str:
        """Проверка связи: возвращает имя бота."""
        me = self.call("getMe")
        self.call("sendMessage", chat_id=self.chat_id,
                  text="Kepil на связи. Сюда будут приходить подтверждения.")
        return me.get("username", "бот")

    def ask_confirmation(self, order: Any, pending: dict[str, Any],
                         rollback: str | None) -> dict[str, Any]:
        """Отправляет карточку действия с кнопками «Подтвердить» и «Вернуть»."""
        client = order.client.get("name", "клиент")
        undo = rollback or "откат невозможен — действие необратимо"
        text = "\n".join([
            f"Требуется подтверждение · заказ {order.id}",
            "",
            f"Клиент: {client}",
            f"Шаг: {pending['title']}",
            f"Действие: {pending['action']}",
            f"Получатель: {pending.get('system') or '—'}",
            f"Если отменить: {undo}",
        ])
        keyboard = {"inline_keyboard": [[
            {"text": "Подтвердить", "callback_data": f"ok:{order.id}"},
            {"text": "Вернуть", "callback_data": f"no:{order.id}"},
        ]]}
        return self.call("sendMessage", chat_id=self.chat_id, text=text,
                         reply_markup=keyboard)

    def notify(self, text: str) -> dict[str, Any]:
        return self.call("sendMessage", chat_id=self.chat_id, text=text)

    # --- приём нажатий ---

    def updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": TIMEOUT,
                                   "allowed_updates": ["callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", **payload) or []

    def answer(self, callback_id: str, text: str) -> None:
        self.call("answerCallbackQuery", callback_query_id=callback_id, text=text)


def parse_press(update: dict[str, Any], chat_id: str) -> tuple[str, str, str] | None:
    """Разбирает нажатие: возвращает (id заказа, решение, id колбэка).

    Нажатия из любого чужого чата игнорируются: бот отвечает только тому, чей
    идентификатор указан в настройках. Иначе кнопку сможет нажать кто угодно,
    кто найдёт бота.
    """
    query = update.get("callback_query")
    if not query:
        return None
    sender_chat = str(((query.get("message") or {}).get("chat") or {}).get("id", ""))
    if sender_chat != str(chat_id):
        return None
    data = query.get("data", "")
    if ":" not in data:
        return None
    decision, order_id = data.split(":", 1)
    if decision not in ("ok", "no"):
        return None
    return order_id, decision, query.get("id", "")


def apply_press(order_id: str, decision: str) -> str:
    """Применяет решение к заказу и возвращает короткий ответ для кнопки."""
    from ..orders import confirm, get

    order = get(order_id)
    if not order.pending:
        return "Уже решено"
    confirm(order, decision == "ok",
            "" if decision == "ok" else "возвращено из Telegram")
    return "Подтверждено" if decision == "ok" else "Возвращено"


def run(bot: Telegram, once: bool = False, pause: float = 1.0) -> None:
    """Цикл ожидания нажатий. Живёт рядом с панелью и переживает обрывы связи."""
    offset: int | None = None
    while True:
        try:
            batch = bot.updates(offset)
        except TelegramError:
            if once:
                return
            time.sleep(5)
            continue

        for update in batch:
            offset = update["update_id"] + 1
            press = parse_press(update, bot.chat_id)
            if not press:
                continue
            order_id, decision, callback_id = press
            try:
                answer = apply_press(order_id, decision)
            except KeyError:
                answer = "Заказ не найден"
            if callback_id:
                try:
                    bot.answer(callback_id, answer)
                except TelegramError:
                    pass
        if once:
            return
        time.sleep(pause)
