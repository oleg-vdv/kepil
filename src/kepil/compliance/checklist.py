"""Чек-лист обследования: что проверяет человек и что уже знает система.

Обследование на соответствие закону — это список вопросов, привязанных к
нормам. Часть ответов на них уже лежит в установке: класс риска и автономности
в паспорте, комплектность документации в пакете, факты остановок и
подтверждений в журнале. Остальное человек обязан ответить сам — происхождение
обучающих данных или страховой договор система знать не может.

Модуль разделяет эти две части. На выходе — отчёт, где у каждого пункта либо
доказательство из установки, либо честная пометка, что нужен человек.

Сам чек-лист — данные: список этапов и пунктов в JSON. Юрисдикция добавляется
файлом, как и пакеты документации. Исполняемого кода в файле нет: пункт
ссылается на **имя** резолвера, а резолверы объявлены здесь и нигде больше.
Файл чек-листа, который приехал извне, не может выполнить ничего своего.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..storage import data_dir

BUILTIN_DIR = Path(__file__).parent / "checklists"

#: Кто отвечает на пункт.
BY_KEPIL = "kepil"        # ответ целиком берётся из установки
BY_HUMAN = "human"        # система знать не может, отвечает человек
BY_BOTH = "mixed"         # система даёт часть, человек подтверждает

#: Состояния пункта в отчёте.
CLOSED = "закрыто"
GAP = "разрыв"
NEEDS_HUMAN = "нужен человек"
UNKNOWN = "резолвер не найден"


@dataclass
class Check:
    id: str
    title: str
    basis: list[str] = field(default_factory=list)
    method: str = ""
    artifact: str = ""
    answered_by: str = BY_HUMAN
    resolver: str = ""
    severity: str = "умеренная"
    common_error: str = ""

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "Check":
        return Check(
            id=str(payload["id"]),
            title=payload["title"],
            basis=list(payload.get("basis", [])),
            method=payload.get("method", ""),
            artifact=payload.get("artifact", ""),
            answered_by=payload.get("answered_by", BY_HUMAN),
            resolver=payload.get("resolver", ""),
            severity=payload.get("severity", "умеренная"),
            common_error=payload.get("common_error", ""),
        )


@dataclass
class Stage:
    id: str
    name: str
    checks: list[Check]
    effort_days: float = 0.0

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "Stage":
        return Stage(
            id=str(payload["id"]),
            name=payload["name"],
            checks=[Check.from_dict(c) for c in payload.get("checks", [])],
            effort_days=float(payload.get("effort_days", 0) or 0),
        )


@dataclass
class Act:
    """Подзаконный акт, на который ссылается чек-лист.

    `verified` — это не формальность. Пока акт не сверен по первоисточнику,
    заключение на него ссылаться не должно: реквизиты в методиках устаревают
    быстрее, чем сами методики.
    """
    name: str
    norm: str = ""
    prg_id: str = ""
    verified: bool = False
    verified_at: str | None = None
    note: str = ""

    @property
    def url(self) -> str:
        return f"https://prg.kz/Document/?doc_id={self.prg_id}" if self.prg_id else ""

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "Act":
        return Act(
            name=payload["name"],
            norm=payload.get("norm", ""),
            prg_id=str(payload.get("prg_id", "")),
            verified=bool(payload.get("verified", False)),
            verified_at=payload.get("verified_at"),
            note=payload.get("note", ""),
        )


@dataclass
class Checklist:
    id: str
    name: str
    jurisdiction: str
    stages: list[Stage]
    acts: list[Act] = field(default_factory=list)
    revision: str = ""
    note: str = ""
    source: str = "встроенный"

    @staticmethod
    def from_dict(payload: dict[str, Any], source: str) -> "Checklist":
        return Checklist(
            id=payload["id"],
            name=payload["name"],
            jurisdiction=payload.get("jurisdiction", ""),
            stages=[Stage.from_dict(s) for s in payload.get("stages", [])],
            acts=[Act.from_dict(a) for a in payload.get("acts", [])],
            revision=payload.get("revision", ""),
            note=payload.get("note", ""),
            source=source,
        )

    def all_checks(self) -> list[Check]:
        return [c for stage in self.stages for c in stage.checks]

    def effort_days(self) -> float:
        return sum(s.effort_days for s in self.stages)

    def unverified_acts(self) -> list[Act]:
        return [a for a in self.acts if not a.verified]


# --- загрузка ---------------------------------------------------------------

def checklists_dir() -> Path:
    return data_dir() / "checklists"


def load_all() -> dict[str, Checklist]:
    """Встроенные чек-листы плюс положенные в каталог данных."""
    found: dict[str, Checklist] = {}
    for directory, source in ((BUILTIN_DIR, "встроенный"),
                              (checklists_dir(), "установленный")):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue                       # битый файл не должен ронять панель
            if "id" in payload and "name" in payload:
                found[payload["id"]] = Checklist.from_dict(payload, source)
    return found


def get(checklist_id: str) -> Checklist:
    everything = load_all()
    if checklist_id not in everything:
        raise KeyError(checklist_id)
    return everything[checklist_id]
