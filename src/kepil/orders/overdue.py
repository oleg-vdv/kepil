"""Карточка, на которую никто не ответил.

Отказ по умолчанию защищает действие: заказ стоит, пока человек не решит.
Читателя он не защищает. Неотвеченная карточка выглядит так же, как только
что отправленная: сервер её принял, в панели она есть, и ничто не говорит,
что её неделю никто не открывал. Доставлено — ещё не значит прочитано.

Поэтому у ожидания есть срок. Просроченная карточка поднимается заново:
в телефон приходит новое сообщение с теми же кнопками, в панели появляется
пометка. Отложить её можно, но только с причиной и до определённого часа.
Откладывание — решение человека, как и подтверждение, и потому пишется в
журнал. Когда срок выходит, карточка возвращается: молчания без даты нет.

Постоянно висящая просрочка поднимает порог для всего, что приходит рядом с
ней. Причина и срок у отложенной карточки нужны ровно для того, чтобы новая
просрочка выглядела новой.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..journal import Journal, JournalEntry

DEFAULT_WAIT_HOURS = 4
MAX_SNOOZE_HOURS = 72


def wait_hours() -> float:
    from ..registry.store import settings
    try:
        hours = float(settings().get("pending_wait_hours") or DEFAULT_WAIT_HOURS)
    except ValueError:
        return DEFAULT_WAIT_HOURS
    return hours if hours > 0 else DEFAULT_WAIT_HOURS


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


def waiting_since(order: Any) -> datetime | None:
    return _parse((order.pending or {}).get("at"))


def due_at(order: Any) -> datetime | None:
    """Когда карточку пора поднимать снова.

    Отложенная — в час, до которого её отложили. Иначе через срок ожидания
    после отправки или после последнего напоминания.
    """
    pending = order.pending or {}
    snoozed = _parse(pending.get("snoozed_until"))
    if snoozed:
        return snoozed
    last = _parse(pending.get("reminded_at")) or waiting_since(order)
    return last + timedelta(hours=wait_hours()) if last else None


def is_overdue(order: Any, now: datetime | None = None) -> bool:
    due = due_at(order)
    return bool(order.pending and due and (now or datetime.now()) >= due)


def waited(order: Any, now: datetime | None = None) -> str:
    """Сколько карточка ждёт, словами: «5 ч», «2 дн 3 ч»."""
    since = waiting_since(order)
    if not since:
        return "?"
    hours = int(((now or datetime.now()) - since).total_seconds() // 3600)
    days, hours = divmod(max(hours, 0), 24)
    return f"{days} дн {hours} ч" if days else f"{hours} ч"


def list_overdue(now: datetime | None = None) -> list[Any]:
    from .service import list_orders
    return [o for o in list_orders() if is_overdue(o, now)]


def snooze(order: Any, reason: str, hours: float,
           now: datetime | None = None) -> datetime:
    """Отложить карточку: с причиной, до определённого часа, с записью в журнал.

    Без причины отказ: отложенная карточка без объяснения — та же тишина.
    Без срока тоже нельзя: срок ограничен сверху, чтобы «потом» не
    превращалось в «никогда».
    """
    from .service import journal_path

    if not order.pending:
        raise ValueError("карточка уже решена: откладывать нечего")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("отложить можно только с причиной")
    if not 0 < hours <= MAX_SNOOZE_HOURS:
        raise ValueError(f"срок — от часа до {MAX_SNOOZE_HOURS} ч")

    now = now or datetime.now()
    until = now + timedelta(hours=hours)
    row = order.pending
    row["snoozed_until"] = until.isoformat(timespec="seconds")
    row["snooze_reason"] = reason
    Journal(journal_path()).append(JournalEntry(
        agent_id=order.agent_id,
        order_id=order.id,
        mandate_id=order.mandate["mandate_id"],
        step=f"{row['step']}:snooze",
        action={"type": row["action"], "target": row["system"]},
        decision="await_human",
        # approved=None: это не подтверждение и не возврат, решение отложено
        human={"required": True, "approved": None, "kind": "snooze",
               "confirmed_by": "operator", "note": reason,
               "until": row["snoozed_until"],
               "at": now.isoformat(timespec="seconds")},
    ))
    order.save()
    return until


def remind_overdue(now: datetime | None = None, client: Any = None) -> list[str]:
    """Поднимает просроченные карточки заново. Возвращает id заказов.

    Без канала напоминать некуда: карточка остаётся просроченной и видна в
    панели, счётчик напоминаний не растёт — иначе он врал бы, что звал.
    """
    from .. import notify
    from ..professions import Profession

    now = now or datetime.now()
    client = client or notify.bot()
    if client is None:
        return []
    raised = []
    for order in list_overdue(now):
        row = order.pending
        rollback = Profession(order.definition()).rollback(row["action"])
        try:
            client.ask_confirmation(order, row, rollback, row.get("head_seen", ""),
                                    waited=waited(order, now),
                                    snooze_reason=row.get("snooze_reason", ""))
        except notify.TelegramError:
            continue
        row["reminded_at"] = now.isoformat(timespec="seconds")
        row["reminders"] = int(row.get("reminders") or 0) + 1
        # срок откладывания вышел — он израсходован, дальше обычный счёт
        row.pop("snoozed_until", None)
        row.pop("snooze_reason", None)
        order.save()
        raised.append(order.id)
    return raised
