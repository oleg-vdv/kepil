"""Расписка о выданной карточке: что она доказывает и что нет."""

import pytest

from kepil import mirror, orders
from kepil.journal import Journal, verify_against_sent
from kepil.mirror.receipt import as_sent_card, describe, read_receipt
from kepil.registry import store

HEAD = "sha256:" + "ab12cd34" * 8


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("KEPIL_DATA", str(tmp_path))
    store.save_settings({"name": "ТОО Kepil", "bin": "123456789012",
                         "operator": "оператор"})
    yield


def letter(head=HEAD, dkim=None, body="Требуется подтверждение"):
    lines = ["From: bot@kepil.kz", "To: audit@example.kz",
             "Subject: Kepil", "Date: Mon, 15 Sep 2026 10:00:00 +0500",
             "Message-ID: <a@kepil.local>", "X-Kepil-Ref: ord-0001:send"]
    if head:
        lines.append(f"X-Kepil-Head: {head}")
    if dkim:
        lines.append(f"DKIM-Signature: {dkim}")
    return ("\n".join(lines) + "\n\n" + body + "\n").encode("utf-8")


SIGNED_WITH_HEAD = ("v=1; a=rsa-sha256; d=kepil.kz; s=mail; "
                    "h=from:to:subject:date:x-kepil-head; b=AAAA")
SIGNED_WITHOUT_HEAD = ("v=1; a=rsa-sha256; d=kepil.kz; s=mail; "
                       "h=from:to:subject:date; b=AAAA")


def test_head_is_read_from_the_header():
    receipt = read_receipt(letter())
    assert receipt["head"] == HEAD and receipt["ref"] == "ord-0001:send"


def test_head_falls_back_to_the_body():
    receipt = read_receipt(letter(head=None, body=f"Журнал на этот момент: {HEAD}"))
    assert receipt["head"] == HEAD


def test_unsigned_letter_proves_only_that_someone_typed_it():
    receipt = read_receipt(letter())
    assert receipt["signature"]["present"] is False
    assert "подписи нет" in describe(receipt)


def test_signature_that_does_not_cover_the_head_is_called_out():
    """Подписано письмо, а не корень — это не расписка о корне."""
    receipt = read_receipt(letter(dkim=SIGNED_WITHOUT_HEAD))
    assert receipt["signature"]["present"] is True
    assert receipt["covers_head"] is False
    assert "в неё не входит" in describe(receipt)


def test_signature_covering_the_head_is_recognised_but_not_verified():
    """Модуль не делает вид, что сверил подпись: для этого нужен ключ из DNS."""
    receipt = read_receipt(letter(dkim=SIGNED_WITH_HEAD))
    assert receipt["covers_head"] is True
    assert receipt["verified"] is False, "проверка подписи здесь не делается"
    assert receipt["signature"]["domain"] == "kepil.kz"
    assert "не сверяли" in describe(receipt)


def test_one_receipt_is_enough_to_show_a_discrepancy():
    """Перечислять ящик не нужно: хватает одного предъявителя."""
    order = orders.create("leads", {"name": "ТОО «Пример»", "bin": "987654321098"})
    while orders.run_next(orders.get(order.id)) is not None:
        if orders.get(order.id).pending:
            break

    receipt = read_receipt(letter(dkim=SIGNED_WITH_HEAD))
    ok, problem = verify_against_sent(Journal(orders.journal_path()),
                                      [as_sent_card(receipt)])
    assert not ok and "которого в журнале нет" in problem


def test_a_receipt_matching_the_journal_passes():
    order = orders.create("leads", {"name": "ТОО «Пример»", "bin": "987654321098"})
    while orders.run_next(orders.get(order.id)) is not None:
        if orders.get(order.id).pending:
            break
    head = orders.get(order.id).pending["head_seen"]
    receipt = read_receipt(letter(head=head, dkim=SIGNED_WITH_HEAD))
    ok, problem = verify_against_sent(Journal(orders.journal_path()),
                                      [as_sent_card(receipt)])
    assert ok, problem
