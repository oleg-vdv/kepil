"""Журнал действий: append-only JSONL с цепочкой SHA-256.

Формат наследуется от AI-Gateway (gateway/core/audit.py) и расширяется полями
мандата, подтверждения человеком и стоимости. Значения персональных данных в
журнал не попадают никогда — только типы, количества и хеши.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterator

GENESIS = "sha256:" + "0" * 64
TZ_ALMATY = timezone(timedelta(hours=5))


def _es_number(value: float) -> str:
    """Число в записи ECMAScript (Number::toString), как требует RFC 8785.

    Python пишет 0.0 как "0.0", а 5e-05 как "5e-05"; JavaScript — "0" и
    "0.00005". Без одинаковой записи хеш одной и той же записи в двух
    реализациях не сойдётся, и внешний верификатор (proofbyte-agent-trace)
    объявит честный журнал подделанным. Цифры берём из repr: он, как и
    JavaScript, даёт кратчайшее точное представление; меняется только
    расстановка точки и экспоненты.
    """
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("NaN и бесконечность в журнал не пишутся")
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    mantissa, _, exp = repr(abs(value)).partition("e")
    whole, _, frac = mantissa.partition(".")
    raw = whole + frac
    digits = raw.lstrip("0")
    # значение = 0.digits × 10^n
    n = len(whole) + int(exp or 0) - (len(raw) - len(digits))
    digits = digits.rstrip("0")
    k = len(digits)
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        text = "0." + "0" * -n + digits
    else:
        e = n - 1
        text = (digits[0] + ("." + digits[1:] if k > 1 else "")
                + "e" + ("+" if e >= 0 else "-") + str(abs(e)))
    return sign + text


def _jcs(value: Any) -> str:
    if value is None or isinstance(value, (bool, str)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _es_number(value)
    if isinstance(value, dict):
        return "{" + ",".join(
            json.dumps(str(k), ensure_ascii=False) + ":" + _jcs(value[k])
            for k in sorted(value)) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_jcs(v) for v in value) + "]"
    raise TypeError(f"тип {type(value).__name__} не сериализуется в журнал")


def _canonical(payload: dict[str, Any]) -> bytes:
    """Каноническая форма записи для хеширования: без поля hash, ключи по порядку.

    Совместима с канонизацией на стороне JavaScript: сортировка ключей,
    отсутствие пробелов, юникод без экранирования, числа по правилам JCS.
    """
    return _jcs({k: v for k, v in payload.items() if k != "hash"}).encode("utf-8")


def entry_hash(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()


@dataclass
class JournalEntry:
    agent_id: str
    action: dict[str, Any]
    decision: str  # allow | deny | await_human
    order_id: str | None = None
    mandate_id: str | None = None
    step: str | None = None
    input_ref: str | None = None
    prompt_version: str | None = None
    model: dict[str, Any] | None = None
    pii: dict[str, Any] | None = None
    human: dict[str, Any] | None = None
    cost_kzt: float = 0.0
    result_ref: str | None = None
    seq: int = 0
    ts: str = field(default_factory=lambda: datetime.now(TZ_ALMATY).isoformat())
    prev_hash: str = GENESIS
    hash: str = ""

    def sealed(self) -> dict[str, Any]:
        payload = {k: v for k, v in asdict(self).items() if v is not None}
        payload["hash"] = entry_hash(payload)
        return payload


class Journal:
    """Файловый журнал. Только добавление; перезапись невозможна по контракту."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq, self._last_hash = self._tail()

    def _tail(self) -> tuple[int, str]:
        records = self.records()
        last = records[-1] if records else None
        return (last["seq"] + 1, last["hash"]) if last else (0, GENESIS)

    def append(self, entry: JournalEntry) -> dict[str, Any]:
        entry.seq = self._seq
        entry.prev_hash = self._last_hash
        record = entry.sealed()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._seq += 1
        self._last_hash = record["hash"]
        return record

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.records())

    def records(self) -> list[dict[str, Any]]:
        """Читаемые записи. Нечитаемая строка не роняет чтение — см. damaged()."""
        return [record for _, record in self._read()[0]]

    def damaged(self) -> list[int]:
        """Номера строк, которые не читаются как запись журнала.

        Такая строка — повреждение: оборванная запись, правка руками, сбой
        диска. Пропустить её молча нельзя, за ней может прятаться удалённая
        запись. Поэтому чтение переживает её, а проверка целостности считает
        поломкой.
        """
        return self._read()[1]

    def _read(self) -> tuple[list[tuple[int, dict[str, Any]]], list[int]]:
        if not self.path.exists():
            return [], []
        good: list[tuple[int, dict[str, Any]]] = []
        bad: list[int] = []
        for number, line in enumerate(
                self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                bad.append(number)
                continue
            if isinstance(record, dict):
                good.append((number, record))
            else:
                bad.append(number)
        return good, bad

    def head(self) -> str:
        """Корень цепочки: то, что раз в сутки подписывается ЭЦП организации."""
        return self._last_hash


def verify_chain(journal: Any) -> tuple[bool, str | None]:
    """Проверяет целостность. Возвращает (ok, описание первой поломки)."""
    damaged = getattr(journal, "damaged", list)()
    if damaged:
        where = ", ".join(str(n) for n in damaged[:5])
        return False, (f"строк не читается как запись: {len(damaged)} "
                       f"(№ {where}) — журнал повреждён или правился вручную")
    prev = GENESIS
    expected_seq = 0
    for record in journal:
        if record.get("prev_hash") != prev:
            return False, f"запись {record.get('seq')}: разрыв цепочки"
        if record.get("seq") != expected_seq:
            return False, f"запись {record.get('seq')}: нарушена нумерация"
        if entry_hash(record) != record.get("hash"):
            return False, f"запись {record.get('seq')}: содержимое изменено"
        prev = record["hash"]
        expected_seq += 1
    return True, None
