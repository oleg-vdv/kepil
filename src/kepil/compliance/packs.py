"""Пакеты документации: тексты отдельно от движка.

Требования к документации на ИИ-систему различаются по странам, а меняются
чаще, чем код. Поэтому здесь тексты — это данные: набор документов с
подстановками, который читается из файла. Добавить юрисдикцию значит положить
файл, а не переписать модуль.

Открытая часть включает универсальный пакет: он опирается на международную
практику (ISO/IEC 42001, статья 12 AI Act) и годится где угодно. Пакеты под
конкретное законодательство — например, под Закон РК № 230-VIII и приказ
№ 95/НҚ — поставляются отдельно и кладутся в каталог данных.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..storage import data_dir

BUILTIN_DIR = Path(__file__).parent / "packs"


@dataclass
class Pack:
    id: str
    name: str
    jurisdiction: str
    required_by_risk: dict[str, list[str]]
    documents: list[dict[str, Any]]
    note: str = ""
    source: str = "встроенный"
    extra: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_dict(payload: dict[str, Any], source: str) -> "Pack":
        return Pack(
            id=payload["id"],
            name=payload["name"],
            jurisdiction=payload.get("jurisdiction", ""),
            required_by_risk=payload.get("required_by_risk", {}),
            documents=payload.get("documents", []),
            note=payload.get("note", ""),
            source=source,
        )

    def required(self, risk_class: str) -> list[str]:
        return self.required_by_risk.get(risk_class,
                                         self.required_by_risk.get("средний", []))


def installed_dir() -> Path:
    """Куда кладутся приобретённые пакеты."""
    return data_dir() / "packs"


def load_all() -> dict[str, Pack]:
    packs: dict[str, Pack] = {}
    for path in sorted(BUILTIN_DIR.glob("*.json")):
        try:
            packs[path.stem] = Pack.from_dict(
                json.loads(path.read_text(encoding="utf-8")), "встроенный")
        except (json.JSONDecodeError, KeyError):
            continue
    directory = installed_dir()
    if directory.exists():
        for path in sorted(directory.glob("*.json")):
            try:
                packs[path.stem] = Pack.from_dict(
                    json.loads(path.read_text(encoding="utf-8")), "установленный")
            except (json.JSONDecodeError, KeyError):
                continue
    return packs


def get(pack_id: str | None = None) -> Pack:
    packs = load_all()
    if pack_id and pack_id in packs:
        return packs[pack_id]
    if not packs:
        raise RuntimeError("не найдено ни одного пакета документации")
    return packs.get("generic") or next(iter(packs.values()))
