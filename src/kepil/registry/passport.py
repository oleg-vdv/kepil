"""Паспорт агента — неизменяемая карточка версии.

Новая версия агента создаёт новую запись; старая сохраняется навсегда.
Состав полей выбран так, чтобы будущая обязательная регистрация агентов
свелась к выгрузке, а не к переделке (см. docs/legal-map.md).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Any

RISK_CLASSES = ("минимальный", "средний", "высокий")   # ст. 17 п. 1
AUTONOMY_CLASSES = ("низкая", "средняя", "высокая")    # ст. 17 п. 2


@dataclass
class AgentPassport:
    agent_id: str
    purpose: str
    does_not: list[str]
    created_by: dict[str, str]
    operated_by: dict[str, str]
    version: dict[str, str]
    risk_class: str = "средний"
    risk_rationale: str = ""
    autonomy_class: str = "средняя"
    autonomy_rationale: str = "все необратимые действия требуют подтверждения человеком"
    models: list[dict[str, Any]] = field(default_factory=list)
    limits: dict[str, float] = field(default_factory=dict)
    risk_review: dict[str, str] = field(default_factory=dict)
    incidents: int = 0
    status: str = "draft"

    def __post_init__(self) -> None:
        if self.risk_class not in RISK_CLASSES:
            raise ValueError(f"класс риска вне ст. 17 п. 1: {self.risk_class}")
        if self.autonomy_class not in AUTONOMY_CLASSES:
            raise ValueError(f"класс автономности вне ст. 17 п. 2: {self.autonomy_class}")
        if self.autonomy_class == "высокая":
            # Особенности создания и эксплуатации таких систем "устанавливаются
            # законами РК", а этих законов нет. Осознанно не заходим (ADR-0002).
            raise ValueError(
                "высокая автономность не допускается: возможность отмены решения "
                "человеком обязательна"
            )

    def fingerprint(self) -> str:
        body = json.dumps(asdict(self), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(body).hexdigest()

    def review_due(self, today: date) -> bool:
        """Ст. 18 п. 1 пп. 4: риски пересматриваются не реже одного раза в год."""
        nxt = self.risk_review.get("next_due")
        return bool(nxt) and date.fromisoformat(nxt) <= today
