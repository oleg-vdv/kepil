"""Фиксация корня цепочки.

Цепочка хешей защищает от правки задним числом только вместе с внешней точкой
отсчёта: без неё можно переписать журнал целиком и пересчитать все хеши. Поэтому
корень периодически фиксируется отдельной записью — якорем.

Юридическую силу якорю даёт подпись ЭЦП организации от НУЦ РК; здесь для неё
оставлено поле и предусмотрена проверка. Пока подписи нет, якорь остаётся
техническим доказательством: он показывает, что журнал на такую-то дату
заканчивался такой-то записью.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .chain import GENESIS, Journal, verify_chain

TZ = timezone(timedelta(hours=5))


def anchors_path(journal: Journal) -> Path:
    return journal.path.with_name(journal.path.stem + "-anchors.jsonl")


def anchor(journal: Journal, signature: dict[str, Any] | None = None) -> dict[str, Any]:
    """Фиксирует текущий корень цепочки. Пустой журнал не фиксируется."""
    entries = list(journal)
    if not entries:
        raise ValueError("журнал пуст: фиксировать нечего")
    record = {
        "ts": datetime.now(TZ).isoformat(timespec="seconds"),
        "seq": entries[-1]["seq"],
        "entries": len(entries),
        "head": entries[-1]["hash"],
        "signature": signature,
    }
    path = anchors_path(journal)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def anchors(journal: Journal) -> list[dict[str, Any]]:
    path = anchors_path(journal)
    if not path.exists():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def witnessed_heads(journal: "Journal") -> list[dict[str, Any]]:
    """Корни цепочки, которые видел человек при подтверждении.

    Карточка подтверждения уходит из процесса наружу — в панель или в Telegram —
    и несёт на себе текущий корень. Вернувшееся решение цитирует тот корень,
    который оно видело, и он попадает в журнал полем `head_seen`.
    """
    out = []
    for record in journal:
        human = record.get("human") or {}
        if human.get("head_seen"):
            out.append({"seq": record.get("seq"), "head_seen": human["head_seen"],
                        "at": human.get("at"), "ref": human.get("channel_ref")})
    return out


def verify_witnesses(journal: "Journal") -> tuple[bool, str | None]:
    """Проверяет, что засвидетельствованные корни всё ещё есть в цепочке.

    Это ловит вторую форму подделки, против которой цепочка сама по себе
    бессильна: журнал обрезают и переписывают заново с верными prev_hash.
    Оставшиеся записи согласуются между собой, и обычная проверка скажет, что
    всё в порядке. Но подтверждения ссылаются на корни, которых в укороченной
    истории больше нет, — и это видно.

    Чего проверка не даёт: тот, кто перепишет и сами ссылки, снова получит
    согласованный файл. Настоящим свидетелем остаётся копия карточки там, куда
    писатель не дотянется, — в переписке оператора. Здесь сверяется только то,
    что доступно изнутри файла.
    """
    seen_hashes = {GENESIS}
    pending: list[dict[str, Any]] = []
    for record in journal:
        human = record.get("human") or {}
        head = human.get("head_seen")
        if head and head not in seen_hashes:
            pending.append({"seq": record.get("seq"), "head": head})
        if record.get("hash"):
            seen_hashes.add(record["hash"])
    if pending:
        first = pending[0]
        return False, (
            f"подтверждение в записи {first['seq']} ссылается на корень "
            f"{first['head'][:23]}…, которого в цепочке нет: история была "
            f"обрезана или переписана (таких подтверждений: {len(pending)})")
    return True, None


def verify_against_sent(journal: "Journal",
                        sent: list[dict[str, Any]]) -> tuple[bool, str | None]:
    """Проверяет журнал по перечню карточек, составленному снаружи.

    Направление здесь принципиально. `verify_witnesses` идёт от журнала наружу и
    потому проверяет только те подтверждения, в которых файл сам признаётся:
    достаточно обрезать историю по последнее подтверждение, и проверять станет
    нечего — цепочка сойдётся, свидетелей ноль, обе проверки зелёные.

    Удаление видно только в обратную сторону. Если перечень отправленных
    карточек составлен вне файла и перечислен целиком, каждая карточка обязана
    найти свой корень в журнале. Пропавшая запись не отменяет карточки.

    Поэтому перечень — аргумент, а не то, что модуль добывает сам. Откуда он
    взят и можно ли ему верить, код решить не может: это и есть то место, где
    доказательство упирается во вторую сторону.
    """
    if not sent:
        # Это не находка, а отсутствие внешней стороны. Смешивать два состояния
        # нельзя: свежая установка, у которой первая карточка ещё не ушла,
        # иначе выглядит как подделка.
        return False, ("внешних карточек нет: сверять журнал не с чем. "
                       "Это не признак удаления — это отсутствие второй стороны")
    hashes = {GENESIS} | {r["hash"] for r in journal if r.get("hash")}
    missing = [card for card in sent if card.get("head") and card["head"] not in hashes]
    if missing:
        first = missing[0]
        return False, (
            f"карточка от {first.get('at', '?')} ({first.get('ref', 'без ссылки')}) "
            f"называет корень {first['head'][:23]}…, которого в журнале нет: "
            f"записи удалены (таких карточек: {len(missing)})")
    return True, None


def sent_cards_path(journal: "Journal") -> Path:
    return journal.path.with_name(journal.path.stem + "-sent.jsonl")


def record_sent(journal: "Journal", head: str, ref: str) -> dict[str, Any]:
    """Локальная копия перечня отправленных карточек.

    Удобство, а не доказательство: файл лежит рядом с журналом, и тот, кто
    переписал один, перепишет и другой. Настоящий перечень живёт в канале, куда
    уходили карточки, и подставляется в verify_against_sent снаружи.
    """
    record = {"at": datetime.now(TZ).isoformat(timespec="seconds"),
              "head": head, "ref": ref}
    with sent_cards_path(journal).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def sent_cards(journal: "Journal") -> list[dict[str, Any]]:
    path = sent_cards_path(journal)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def verify(journal: Journal) -> tuple[bool, str | None]:
    """Проверяет цепочку и все зафиксированные корни.

    Ловит подмену, которую одна цепочка пропустила бы: журнал переписан целиком,
    хеши пересчитаны, но старый зафиксированный корень в нём больше не найти.
    """
    ok, error = verify_chain(journal)
    if not ok:
        return False, error

    by_seq = {record["seq"]: record["hash"] for record in journal}
    for item in anchors(journal):
        actual = by_seq.get(item["seq"])
        if actual is None:
            return False, (f"якорь от {item['ts']}: записи {item['seq']} "
                           f"больше нет в журнале")
        if actual != item["head"]:
            return False, (f"якорь от {item['ts']}: запись {item['seq']} "
                           f"изменилась после фиксации")

    return verify_witnesses(journal)
