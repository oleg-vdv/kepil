"""Шлюз действий — единственная точка выхода агента наружу.

Расширяет шлюз AI-Gateway (обращения к моделям) на любые действия: чтение
внешних систем, генерацию документов, отправку, запись. Сценарий агента не
может обойти этот слой — паттерн защитной оболочки из AffectGuard-HRI.

Порядок проверок соответствует разделу 5 технического задания.
Принцип fail-closed: любая ошибка проверки означает отказ, а не пропуск.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from ..journal import Journal, JournalEntry
from ..mandate import Mandate, MandateError


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    AWAIT_HUMAN = "await_human"


@dataclass
class ActionRequest:
    action: str                     # 'read:goszakup', 'generate:document', 'send:package'
    system: str | None = None       # домен или endpoint
    payload_ref: str | None = None  # хеш содержимого, не само содержимое
    cost_kzt: float = 0.0
    amount_kzt: float = 0.0


class ActionGateway:
    def __init__(
        self,
        journal: Journal,
        passport_is_active: Callable[[str], bool],
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._journal = journal
        self._passport_is_active = passport_is_active
        self._now = now

    def check(self, mandate: Mandate, request: ActionRequest) -> tuple[Decision, str]:
        """Возвращает решение и основание. Ничего не выполняет."""
        try:
            if not self._passport_is_active(mandate.agent_id):
                return Decision.DENY, "паспорт агента неактивен"
            if not mandate.is_valid_at(self._now()):
                return Decision.DENY, "мандат недействителен по сроку"
            if not mandate.permits(request.action, request.system):
                target = f" для системы '{request.system}'" if request.system else ""
                return Decision.DENY, (
                    f"действие '{request.action}' не разрешено мандатом{target}"
                )
            if request.cost_kzt:
                mandate.spend("llm_cost_kzt", request.cost_kzt)
            if request.amount_kzt:
                mandate.spend("amount_kzt", request.amount_kzt)
            if mandate.needs_human(request.action):
                return (Decision.AWAIT_HUMAN,
                        "необратимое действие: требуется подтверждение человека")
            return Decision.ALLOW, "в пределах мандата"
        except MandateError as exc:
            return Decision.DENY, str(exc)
        except Exception as exc:  # fail-closed
            return Decision.DENY, f"ошибка проверки, отказ по умолчанию: {exc!r}"

    def record(self, mandate: Mandate, request: ActionRequest,
               decision: Decision, reason: str, **extra: Any) -> dict[str, Any]:
        return self._journal.append(JournalEntry(
            agent_id=mandate.agent_id,
            order_id=mandate.order_id,
            mandate_id=mandate.mandate_id,
            action={"type": request.action, "target": request.system, "reason": reason},
            decision=decision.value,
            cost_kzt=request.cost_kzt,
            input_ref=request.payload_ref,
            **extra,
        ))
