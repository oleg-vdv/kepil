"""Зеркало пути отправки: копия карточки там, где писатель её не правит."""

import email.message

import pytest

from kepil import mirror, orders
from kepil.journal import Journal, verify_against_sent
from kepil.mirror.mail import MailMirror, MirrorError, enumerate_cards
from kepil.registry import store


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("KEPIL_DATA", str(tmp_path))
    store.save_settings({"name": "ТОО Kepil", "bin": "123456789012",
                         "operator": "оператор"})
    yield


def turn_mirror_on(**extra):
    store.save_settings({**store.settings(), "mirror_host": "smtp.local",
                         "mirror_to": "audit@example.kz",
                         "mirror_user": "bot@example.kz", **extra})


def waiting_order():
    order = orders.create("leads", {"name": "ТОО «Пример»", "bin": "987654321098"})
    while orders.run_next(orders.get(order.id)) is not None:
        if orders.get(order.id).pending:
            break
    return orders.get(order.id)


# --- выключено по умолчанию -------------------------------------------------

def test_mirror_is_off_until_configured():
    assert mirror.configured() is False
    assert mirror.mirror() is None
    assert mirror.send_copy("sha256:" + "ab" * 32, "ref", "тело") is None


# --- письмо -----------------------------------------------------------------

def test_head_travels_in_a_header_not_only_in_the_body():
    """Перечисление не должно зависеть от переносов строк в теле письма."""
    head = "sha256:" + "ab12cd34" * 8
    message = MailMirror("smtp.local", 587, "u", "p", "u@x", "a@y").build(
        head, "ord-0001:step", "тело карточки")
    assert message["X-Kepil-Head"] == head
    assert head in message.get_content()


def test_send_returns_the_message_id_for_walking_outward():
    sent: list[email.message.EmailMessage] = []
    client = MailMirror("smtp.local", 587, "u", "p", "u@x", "a@y",
                        transport=sent.append)
    result = client.send("sha256:" + "ab" * 32, "ord-0001", "тело")
    assert sent and result["message_id"]


def test_transport_failure_becomes_a_mirror_error():
    def explode(_message):
        raise OSError("сеть недоступна")
    client = MailMirror("smtp.local", 587, "u", "p", "u@x", "a@y", transport=explode)
    with pytest.raises(MirrorError):
        client.send("sha256:" + "ab" * 32, "ord-0001", "тело")


# --- громкий сбой -----------------------------------------------------------

def test_failed_mirror_stops_the_order(monkeypatch):
    """Пропущенная копия сдвигает потерю на шаг наружу и делает её тихой.

    Поэтому правило обратно уведомлению: не записалось — заказ останавливается.
    """
    turn_mirror_on()

    def explode(*_args, **_kwargs):
        raise MirrorError("копия карточки не записана")

    monkeypatch.setattr(mirror, "send_copy", explode)
    order = waiting_order()
    assert order.status == "stopped", "заказ обязан встать"

    last = list(Journal(orders.journal_path()))[-1]
    assert last["action"]["type"] == "stop:order"
    assert "зеркало недоступно" in last["human"]["note"]


def test_working_mirror_lets_the_order_wait_for_a_person(monkeypatch):
    turn_mirror_on()
    written: list[tuple] = []
    monkeypatch.setattr(mirror, "send_copy",
                        lambda head, ref, body: written.append((head, ref)) or {})
    order = waiting_order()
    assert order.status == "awaiting"
    assert written and written[0][0] == order.pending["head_seen"]


def test_notification_failure_still_does_not_stop_the_order(monkeypatch):
    """Разные правила для разных задач: уведомление падать заказу не мешает."""
    from kepil import notify

    def explode(_order):
        raise RuntimeError("Telegram недоступен")

    monkeypatch.setattr(notify, "on_pending", explode)
    order = waiting_order()
    assert order.status == "awaiting"


# --- перечисление -----------------------------------------------------------

class FakeIMAP:
    """Ящик, который перечисляется целиком — включая письма без ответа."""

    def __init__(self, messages):
        self.messages = messages

    def login(self, *_):
        return "OK", []

    def select(self, *_args, **_kwargs):
        return "OK", []

    def search(self, *_args):
        return "OK", [b" ".join(str(i).encode() for i in range(len(self.messages)))]

    def fetch(self, number, _spec):
        index = int(number)
        return "OK", [(b"", self.messages[index].encode("utf-8"))]

    def logout(self):
        return "OK", []


def test_enumeration_returns_cards_nobody_answered():
    """Карточка без ответа — ровно та, чьё исчезновение и надо поймать."""
    head_answered = "sha256:" + "11" * 32
    head_ignored = "sha256:" + "22" * 32
    box = FakeIMAP([
        f"Date: Mon, 15 Sep 2026 10:00:00 +0500\nX-Kepil-Head: {head_answered}\n"
        f"X-Kepil-Ref: ord-0001:send\nMessage-ID: <a@kepil.local>\n",
        f"Date: Mon, 15 Sep 2026 11:00:00 +0500\nX-Kepil-Head: {head_ignored}\n"
        f"X-Kepil-Ref: ord-0002:send\nMessage-ID: <b@kepil.local>\n",
    ])
    cards = enumerate_cards("imap.local", "auditor", "pw", opener=lambda: box)
    assert [c["head"] for c in cards] == [head_answered, head_ignored]
    assert cards[1]["ref"] == "ord-0002:send"


def test_enumeration_feeds_the_outside_in_check():
    """Перечень из ящика подаётся в проверку как есть, без правок верификатора."""
    order = waiting_order()
    head = order.pending["head_seen"]
    box = FakeIMAP([f"Date: Mon, 15 Sep 2026 10:00:00 +0500\n"
                    f"X-Kepil-Head: {head}\nX-Kepil-Ref: {order.id}\n"])
    cards = enumerate_cards("imap.local", "auditor", "pw", opener=lambda: box)

    ok, problem = verify_against_sent(Journal(orders.journal_path()), cards)
    assert ok, problem

    # а теперь письмо о карточке, записей которой в журнале нет
    box.messages.append("Date: Mon, 15 Sep 2026 12:00:00 +0500\n"
                        "X-Kepil-Head: sha256:" + "ff" * 32 + "\nX-Kepil-Ref: ord-0099\n")
    cards = enumerate_cards("imap.local", "auditor", "pw", opener=lambda: box)
    ok, problem = verify_against_sent(Journal(orders.journal_path()), cards)
    assert not ok and "которого в журнале нет" in problem
