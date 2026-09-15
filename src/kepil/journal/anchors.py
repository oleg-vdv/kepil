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
