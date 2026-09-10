"""Профессия «тендерный пакет» — первая в работе.

Границы сознательные: агент не подаёт заявку и не подписывает документы.
Подача выполняется клиентом его ЭЦП (ADR-0001).
"""

from __future__ import annotations

from typing import Any

from ..registry.passport import AgentPassport
from .base import Profession

PASSPORT = AgentPassport(
    agent_id="kepil.tender.v1",
    purpose="Подготовка пакета документов для участия в государственных закупках",
    does_not=[
        "не подаёт заявку на портал",
        "не подписывает документы",
        "не обращается к системам вне белого списка",
        "не хранит и не использует ЭЦП клиента",
    ],
    created_by={"bin": "000000000000", "name": "Kepil"},
    operated_by={"bin": "000000000000", "role": "владелец системы"},
    version={"agent": "1.0.0", "released_at": "2026-09-10"},
    risk_class="средний",
    risk_rationale=(
        "ст. 17 п. 1: возможен материальный ущерб (несостоявшееся участие), "
        "чрезвычайная ситуация исключена"
    ),
    autonomy_class="средняя",
    limits={"documents": 20, "llm_cost_kzt": 3000},
    risk_review={"last": "2026-09-10", "next_due": "2027-09-10"},
    status="draft",
)


class TenderProfession(Profession):
    id = "tender"
    passport = PASSPORT

    def intake(self, order: dict[str, Any]) -> list[str]:
        return [
            "профиль компании: лицензии и их категории",
            "опыт: реестр исполненных договоров",
            "финансовые показатели за последний период",
            "техника и персонал",
            "регистрации: национальный каталог, НТИН, реестр производителей",
            "интересующие предметы закупок и регионы",
        ]

    def steps(self) -> list[str]:
        return [
            "select_announcements",   # отбор объявлений
            "parse_specification",    # разбор технической спецификации
            "check_eligibility",      # вердикт о проходимости
            "detect_tailoring",       # признаки требований под конкурента
            "assemble_package",       # сборка пакета
            "handover_to_client",     # передача клиенту на подпись и подачу
            "post_result",            # разбор итогов, при отклонении — обжалование
        ]

    def irreversible(self) -> list[str]:
        return ["send:*", "publish:*", "write:external"]

    def rollback(self, action: str) -> str | None:
        return {
            "send:package": "уведомить получателя об отзыве и направить корректный пакет",
            "publish:complaint": None,  # публичную жалобу отозвать нельзя
        }.get(action, "удалить созданный черновик")

    def deliver(self, order: dict[str, Any]) -> dict[str, Any]:
        return {
            "order_id": order.get("order_id"),
            "files": [],
            "checklist": ["что подписать", "что приложить вручную", "срок подачи"],
            "ai_marking": {
                "machine_readable": {"generated_by": "kepil.tender.v1"},
                "visible": ("Документ подготовлен с использованием системы "
                            "искусственного интеллекта (ст. 21 Закона РК № 230-VIII)"),
            },
        }
