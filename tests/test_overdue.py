"""Неотвеченная карточка: срок ожидания, напоминание, откладывание с причиной."""

from datetime import datetime, timedelta

import pytest

from kepil import orders
from kepil.journal import Journal
from kepil.meter.counters import Counters
from kepil.notify import Telegram
from kepil.registry import store


class FakeTelegram:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def __call__(self, url, payload):
        if self.fail:
            return {"ok": False, "description": "нет связи"}
        self.sent.append(payload)
        return {"ok": True, "result": {"message_id": len(self.sent)}}


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("KEPIL_DATA", str(tmp_path))
    store.save_settings({"name": "Kepil", "bin": "123456789012",
                         "operator": "оператор", "pending_wait_hours": "4"})
    yield


def waiting_order():
    order = orders.create("leads", {"name": "Клиника «Пример»", "bin": "987654321098"})
    while orders.run_next(orders.get(order.id)) is not None:
        if orders.get(order.id).pending:
            break
    return orders.get(order.id)


def sent_at(order):
    return datetime.fromisoformat(order.pending["at"])


def test_fresh_card_is_not_overdue():
    order = waiting_order()
    assert not orders.is_overdue(order, sent_at(order) + timedelta(hours=3))


def test_card_unanswered_past_the_wait_is_overdue():
    order = waiting_order()
    assert orders.is_overdue(order, sent_at(order) + timedelta(hours=4))
    assert [o.id for o in orders.list_overdue(sent_at(order) + timedelta(hours=5))] == [order.id]


def test_overdue_card_is_raised_again_with_the_same_buttons():
    """Напоминание — та же карточка: кнопки работают, корень тот же."""
    order = waiting_order()
    later = sent_at(order) + timedelta(hours=26)
    transport = FakeTelegram()
    raised = orders.remind_overdue(later, Telegram("t", "42", transport))

    assert raised == [order.id]
    text = transport.sent[0]["text"]
    assert text.startswith("Ждёт решения 1 дн 2 ч")
    assert order.pending["head_seen"] in text
    buttons = transport.sent[0]["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"].startswith(f"ok:{order.id}:")

    order = orders.get(order.id)
    assert order.pending["reminders"] == 1
    assert not orders.is_overdue(order, later + timedelta(hours=3)), \
        "после напоминания счёт идёт заново"
    assert orders.is_overdue(order, later + timedelta(hours=4))


def test_reminder_does_not_count_when_the_channel_is_down():
    """Счётчик напоминаний не должен утверждать, что звал, если не дозвался."""
    order = waiting_order()
    later = sent_at(order) + timedelta(hours=5)
    assert orders.remind_overdue(later, Telegram("t", "42", FakeTelegram(fail=True))) == []
    order = orders.get(order.id)
    assert "reminders" not in order.pending
    assert orders.is_overdue(order, later)


def test_snooze_requires_a_reason():
    order = waiting_order()
    with pytest.raises(ValueError, match="причин"):
        orders.snooze(order, "  ", 24)


def test_snooze_requires_an_end():
    order = waiting_order()
    with pytest.raises(ValueError, match="срок"):
        orders.snooze(order, "жду ответа юриста", 0)
    with pytest.raises(ValueError, match="срок"):
        orders.snooze(order, "жду ответа юриста", 24 * 30)


def test_snooze_is_a_human_decision_in_the_journal():
    order = waiting_order()
    now = sent_at(order) + timedelta(hours=5)
    orders.snooze(order, "жду ответа юриста", 24, now)

    record = list(Journal(orders.journal_path()))[-1]
    assert record["step"].endswith(":snooze")
    assert record["human"]["kind"] == "snooze"
    assert record["human"]["approved"] is None
    assert record["human"]["note"] == "жду ответа юриста"
    assert "head_seen" not in record["human"], "откладывание не свидетельствует корень"
    ok, problem = orders.verify_journal()
    assert ok, problem


def test_snoozed_card_comes_back_loud_when_the_snooze_ends():
    order = waiting_order()
    now = sent_at(order) + timedelta(hours=5)
    orders.snooze(order, "жду ответа юриста", 24, now)
    order = orders.get(order.id)

    assert not orders.is_overdue(order, now + timedelta(hours=23))
    assert orders.is_overdue(order, now + timedelta(hours=24))

    transport = FakeTelegram()
    orders.remind_overdue(now + timedelta(hours=24), Telegram("t", "42", transport))
    assert "Было отложено: жду ответа юриста. Срок вышел." in transport.sent[0]["text"]
    assert "snoozed_until" not in orders.get(order.id).pending, "срок израсходован"


def test_snooze_is_not_counted_as_an_action_or_a_decision():
    order = waiting_order()
    counters = Counters()
    for record in Journal(orders.journal_path()):
        counters.add_record(record)
    before = (counters.actions, counters.confirmations, counters.returns)

    orders.snooze(order, "жду ответа юриста", 24)
    counters = Counters()
    for record in Journal(orders.journal_path()):
        counters.add_record(record)
    assert (counters.actions, counters.confirmations, counters.returns) == before


def test_answered_card_cannot_be_snoozed():
    order = waiting_order()
    orders.confirm(order, True)
    with pytest.raises(ValueError, match="решена"):
        orders.snooze(orders.get(order.id), "поздно", 24)


# --- панель ------------------------------------------------------------------

def test_panel_snoozes_with_reason_and_refuses_without():
    from kepil.admin import app
    from kepil.admin.app import Request, resolve

    order = waiting_order()
    assert resolve("POST", f"/orders/{order.id}/snooze") is not None

    refused = app.order_snooze(Request("/x", {"reason": "", "hours": "24"},
                                       {"id": order.id}))
    assert refused.status == 200 and "причин" in refused.body
    assert "snoozed_until" not in orders.get(order.id).pending

    done = app.order_snooze(Request("/x", {"reason": "жду юриста", "hours": "24"},
                                    {"id": order.id}))
    assert done.redirect == f"/orders/{order.id}"
    page = app.order_view(Request("/", {}, {"id": order.id})).body
    assert "Отложено до" in page and "жду юриста" in page
