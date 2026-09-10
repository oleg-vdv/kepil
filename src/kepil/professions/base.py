"""Контракт профессии.

Профессия — сценарий с фиксированными шагами, а не свободный автономный цикл.
Свободный цикл нельзя ни проверить, ни защитить на аудите.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..registry.passport import AgentPassport


class Profession(ABC):
    id: str
    passport: AgentPassport

    @abstractmethod
    def intake(self, order: dict[str, Any]) -> list[str]:
        """Чек-лист: что нужно получить от клиента до старта."""

    @abstractmethod
    def steps(self) -> list[str]:
        """Шаги сценария в порядке выполнения."""

    @abstractmethod
    def irreversible(self) -> list[str]:
        """Типы действий, требующие подтверждения человеком."""

    @abstractmethod
    def rollback(self, action: str) -> str | None:
        """Компенсирующее действие. None означает: откат невозможен."""

    @abstractmethod
    def deliver(self, order: dict[str, Any]) -> dict[str, Any]:
        """Результат с маркировкой ИИ (ст. 21 п. 2)."""
