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


def _jcs_numbers(value: Any) -> Any:
    """Приводит числа к форме, одинаковой в Python и JavaScript.

    Python пишет float 0.0 как "0.0", JavaScript — как "0". Без нормализации
    хеш одной и той же записи в двух реализациях не сойдётся, и внешний
    верификатор (proofbyte-agent-trace) объявит целый журнал подделанным.
    Приводим целые float к int — это подмножество RFC 8785 (JCS), достаточное
    для наших записей.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _jcs_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jcs_numbers(v) for v in value]
    return value


def _canonical(payload: dict[str, Any]) -> bytes:
    """Каноническая форма записи для хеширования: без поля hash, ключи по порядку.

    Совместима с канонизацией на стороне JavaScript: сортировка ключей,
    отсутствие пробелов, юникод без экранирования, числа по правилам JCS.
    """
    body = _jcs_numbers({k: v for k, v in payload.items() if k != "hash"})
    return json.dumps(body, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


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
