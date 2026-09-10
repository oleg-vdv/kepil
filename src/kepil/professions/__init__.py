"""Профессии: что агент умеет делать.

Профессия задаётся описанием (JSON), а не классом, поэтому её можно создать и
изменить в админ-панели, не трогая ядро.
"""

from .base import Profession
from .definition import (
    ProfessionDefinition,
    Step,
    delete,
    duplicate,
    get,
    load_all,
    save,
)

__all__ = [
    "Profession", "ProfessionDefinition", "Step",
    "load_all", "get", "save", "delete", "duplicate",
]


def load(profession_id: str) -> Profession:
    """Готовая к работе профессия по идентификатору."""
    return Profession(get(profession_id))
