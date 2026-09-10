"""Мандат — машиночитаемая доверенность агента на конкретный заказ.

Принцип: всё, что не разрешено явно, запрещено. Проверяется шлюзом на каждом
действии, а не сценарием агента.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class MandateError(Exception):
    """Действие вне мандата."""


@dataclass
class Mandate:
    mandate_id: str
    agent_id: str
    order_id: str
    principal: dict[str, Any]
    allowed_actions: list[str]
    allowed_systems: list[str]
    valid_from: datetime
    valid_until: datetime
    human_confirmation_required: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)
    limits: dict[str, float] = field(default_factory=dict)
    _spent: dict[str, float] = field(default_factory=dict, repr=False)

    def is_valid_at(self, now: datetime) -> bool:
        return self.valid_from <= now <= self.valid_until

    def permits(self, action: str, system: str | None = None) -> bool:
        if any(fnmatch.fnmatch(action, p) for p in self.forbidden_actions):
            return False
        if not any(fnmatch.fnmatch(action, p) for p in self.allowed_actions):
            return False
        if system is not None and not any(
            fnmatch.fnmatch(system, p) for p in self.allowed_systems
        ):
            return False
        return True

    def needs_human(self, action: str) -> bool:
        return any(fnmatch.fnmatch(action, p) for p in self.human_confirmation_required)

    def remaining(self, key: str) -> float:
        return self.limits.get(key, 0.0) - self._spent.get(key, 0.0)

    def spend(self, key: str, amount: float) -> None:
        """Списывает лимит; бросает MandateError, если лимита нет или он исчерпан."""
        if key not in self.limits:
            raise MandateError(f"лимит '{key}' не установлен мандатом")
        if self._spent.get(key, 0.0) + amount > self.limits[key]:
            raise MandateError(
                f"лимит '{key}' исчерпан: предел {self.limits[key]}, "
                f"запрошено ещё {amount}"
            )
        self._spent[key] = self._spent.get(key, 0.0) + amount
