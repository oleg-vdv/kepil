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

from .chain import Journal, verify_chain

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
    return True, None
