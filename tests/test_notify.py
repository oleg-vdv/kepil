"""Подтверждения в телефон: карточка, нажатие, чужой чат, обрыв связи."""

import pytest

from kepil import notify, orders
from kepil.notify import Telegram, TelegramError, apply_press, parse_press
from kepil.registry import store


class FakeTelegram:
    """Транспорт вместо сети: запоминает вызовы и отдаёт заготовленные ответы."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, url, payload):
        method = url.rsplit("/", 1)[-1]
        self.calls.append((method, payload))
        return self.responses.get(method, {"ok": True, "result": {}})

    def payload(self, method):
        return next(p for m, p in self.calls if m == method)


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("KEPIL_DATA", str(tmp_path))
    store.save_settings({"name": "Kepil", "bin": "123456789012",
                         "operator": "оператор"})
    yield


def waiting_order():
    order = orders.create("leads", {"name": "Клиника «Пример»", "bin": "987654321098"})
    while orders.run_next(orders.get(order.id)) is not None:
        if orders.get(order.id).pending:
            break
    return orders.get(order.id)


# --- карточка ---------------------------------------------------------------

def test_confirmation_card_holds_what_the_operator_needs():
    transport = FakeTelegram()
    order = waiting_order()
    Telegram("t", "42", transport).ask_confirmation(
        order, order.pending, "отправить уточняющее сообщение")

    payload = transport.payload("sendMessage")
    assert payload["chat_id"] == "42"
    assert order.id in payload["text"]
    assert "Клиника «Пример»" in payload["text"]
    assert order.pending["action"] in payload["text"]
    assert "отправить уточняющее" in payload["text"], "оператор должен видеть цену отмены"

    buttons = payload["reply_markup"]["inline_keyboard"][0]
    assert [b["callback_data"] for b in buttons] == [f"ok:{order.id}", f"no:{order.id}"]


def test_irreversible_action_says_so_in_the_card():
    transport = FakeTelegram()
    order = waiting_order()
    Telegram("t", "42", transport).ask_confirmation(order, order.pending, None)
    assert "необратимо" in transport.payload("sendMessage")["text"]


# --- нажатия ----------------------------------------------------------------

def press(order_id, decision="ok", chat="42"):
    return {"update_id": 1, "callback_query": {
        "id": "cb1", "data": f"{decision}:{order_id}",
        "message": {"chat": {"id": chat}}}}


def test_press_from_the_owner_is_accepted():
    assert parse_press(press("ord-0001"), "42") == ("ord-0001", "ok", "cb1")


def test_press_from_a_stranger_is_ignored():
    assert parse_press(press("ord-0001", chat="999"), "42") is None, (
        "иначе кнопку нажмёт любой, кто нашёл бота")


def test_garbage_is_ignored():
    assert parse_press({"update_id": 1}, "42") is None
    assert parse_press({"callback_query": {"data": "нет-двоеточия",
                                           "message": {"chat": {"id": "42"}}}}, "42") is None


def test_confirmation_from_the_phone_moves_the_order():
    order = waiting_order()
    assert apply_press(order.id, "ok") == "Подтверждено"
    assert orders.get(order.id).pending is None


def test_return_from_the_phone_is_recorded():
    order = waiting_order()
    assert apply_press(order.id, "no") == "Возвращено"
    from kepil.journal import Journal
    last = [r for r in Journal(orders.journal_path()) if r.get("human")][-1]
    assert last["decision"] == "deny"
    assert "Telegram" in last["human"]["note"]


def test_second_press_changes_nothing():
    order = waiting_order()
    apply_press(order.id, "ok")
    assert apply_press(order.id, "ok") == "Уже решено"


# --- поведение при сбоях ----------------------------------------------------

def test_broken_channel_does_not_break_the_order(monkeypatch):
    store.save_settings({**store.settings(), "telegram_token": "t",
                         "telegram_chat_id": "42"})

    def explode(url, payload):
        raise TelegramError("нет связи с Telegram")

    monkeypatch.setattr("kepil.notify.telegram._http", explode)
    order = waiting_order()   # уведомление падает, заказ обязан выжить
    assert order.status == "awaiting"
    assert order.pending is not None


def test_channel_is_optional():
    assert notify.configured() is False
    assert notify.bot() is None
    notify.on_pending(waiting_order())   # без канала это просто ничего не делает


def test_channel_turns_on_from_settings():
    store.save_settings({**store.settings(), "telegram_token": "t",
                         "telegram_chat_id": "42"})
    assert notify.configured() is True
    assert notify.bot().chat_id == "42"
