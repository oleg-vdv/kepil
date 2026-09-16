"""Зеркало пути отправки: копия карточки туда, где её нельзя переписать.

Карточка подтверждения — единственный артефакт, рождающийся за пределами
процесса, который ведёт журнал. Но у Telegram есть изъян: бот не может
перечислить то, что отправил. Нажатие возвращает только ту карточку, на которую
нажали, а карточки, ушедшие и оставшиеся без ответа, — ровно те, чьё исчезновение
и должна поймать проверка, — не возвращаются никогда.

Поэтому копия каждой карточки пишется на второй адрес, **читать** который
писатель журнала не управляет. Проверяющий перечисляет этот адрес целиком и
подаёт перечень в `verify_against_sent`. Граница сохраняется: код по-прежнему
принимает перечень аргументом и по-прежнему не добывает его сам.

Почта выбрана потому, что оба конца есть в стандартной библиотеке: `smtplib`
отправляет, `imaplib` перечисляет папку целиком, включая письма, на которые
никто не отвечал. Ничего сверх того, от чего проект уже зависит, не добавляется.

Правило, обратное уведомлениям: **сбой зеркала громкий**. Уведомление может не
дойти, и заказ обязан это пережить — его задача дотянуться до человека. Зеркало
производит доказательство, и молчаливый пропуск записи сдвигает потерю на один
шаг наружу, где её снова не видно. Поэтому не записалось — карточка не уходит.
"""

from __future__ import annotations

from typing import Any

from .mail import MailMirror, MirrorError, enumerate_cards

__all__ = ["MailMirror", "MirrorError", "enumerate_cards", "configured", "mirror",
           "send_copy"]


def _settings() -> dict[str, str]:
    from ..registry import store
    return store.settings()


def configured() -> bool:
    data = _settings()
    return bool(data.get("mirror_host") and data.get("mirror_to"))


def mirror() -> "MailMirror | None":
    if not configured():
        return None
    data = _settings()
    return MailMirror(
        host=data["mirror_host"],
        port=int(data.get("mirror_port") or 587),
        user=data.get("mirror_user", ""),
        password=data.get("mirror_password", ""),
        sender=data.get("mirror_from") or data.get("mirror_user", ""),
        to=data["mirror_to"],
    )


def send_copy(head: str, ref: str, body: str) -> dict[str, Any] | None:
    """Копия карточки на внешний адрес. Возвращает None, если зеркало выключено.

    Исключение MirrorError наружу не глотается: вызывающая сторона обязана
    остановить заказ, а не продолжить без доказательства.
    """
    client = mirror()
    if client is None:
        return None
    return client.send(head, ref, body)
