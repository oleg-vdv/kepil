"""Профессия — исполняемая обёртка над описанием.

Один класс на все профессии: поведение задаётся описанием, а не наследованием.
Новая профессия не требует ни строчки кода — только файла описания, поэтому её
можно создать прямо в админ-панели.

Профессия остаётся сценарием с фиксированными шагами, а не свободным автономным
циклом: свободный цикл нельзя ни проверить, ни защитить на аудите.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ..registry.passport import AgentPassport
from .definition import ProfessionDefinition, Step


@dataclass
class Profession:
    definition: ProfessionDefinition

    @property
    def id(self) -> str:
        return self.definition.id

    @property
    def name(self) -> str:
        return self.definition.name

    def intake(self) -> list[str]:
        """Чек-лист: что нужно получить от клиента до старта."""
        return list(self.definition.intake)

    def steps(self) -> list[Step]:
        """Шаги сценария в порядке выполнения."""
        return list(self.definition.steps)

    def irreversible(self) -> list[str]:
        """Типы действий, требующие подтверждения человеком."""
        return list(self.definition.irreversible)

    def rollback(self, action: str) -> str | None:
        """Компенсирующее действие. None означает: откат невозможен."""
        if action in self.definition.rollback:
            return self.definition.rollback[action] or None
        return "удалить созданный черновик"

    def passport(self, operator: dict[str, str], version: str = "1.0.0",
                 released: str | None = None) -> AgentPassport:
        """Паспорт версии агента для этой профессии.

        Класс автономности всегда «средняя»: любое необратимое действие уходит
        человеку, а конструктор паспорта не примет «высокую» (ADR-0002).
        """
        released = released or date.today().isoformat()
        return AgentPassport(
            agent_id=f"kepil.{self.definition.id}.v{version.split('.')[0]}",
            purpose=self.definition.purpose,
            does_not=list(self.definition.does_not),
            created_by=dict(operator),
            operated_by={**operator, "role": "владелец системы"},
            version={"agent": version, "released_at": released},
            risk_class=self.definition.risk_class,
            risk_rationale=self.definition.risk_rationale,
            autonomy_class="средняя",
            limits=dict(self.definition.limits),
            risk_review={
                "last": released,
                "next_due": (date.fromisoformat(released)
                             + timedelta(days=365)).isoformat(),
            },
            status="active",
        )

    def deliver(self, order: dict[str, Any]) -> dict[str, Any]:
        """Результат с маркировкой ИИ (ст. 21 п. 2)."""
        return {
            "order_id": order.get("id"),
            "profession": self.definition.id,
            "deliverable": self.definition.deliverable,
            "ai_marking": {
                "machine_readable": {"generated_by": f"kepil.{self.definition.id}"},
                "visible": ("Результат подготовлен с использованием системы "
                            "искусственного интеллекта (ст. 21 Закона РК № 230-VIII)"),
            },
        }
