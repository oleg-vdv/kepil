"""Профессия как описание, а не как код.

Профессия — это то, что агент умеет делать: последовательность шагов, границы
полномочий, лимиты и правила отката. Всё это данные, а не программа: добавить
профессию значит положить JSON-файл, а не написать класс. Так профессии можно
менять из админ-панели, не касаясь ядра.

Опасные вещи описанием не задаются: класс автономности проверяется паспортом,
необратимые действия всегда уходят человеку, а шлюз сверяет каждое действие с
мандатом независимо от того, что написано в описании.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from ..storage import data_dir, list_json, read_json, write_json

BUILTIN_DIR = Path(__file__).parent / "definitions"

ACTION_RE = re.compile(r"^[a-z_]+:[a-z_*][a-z_*.]*$")


@dataclass
class Step:
    id: str
    title: str
    action: str
    system: str | None = None
    cost_kzt: float = 0.0

    @staticmethod
    def parse(line: str, index: int) -> "Step":
        """Разбирает строку админ-панели: 'действие | заголовок | система | цена'."""
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0]:
            raise ValueError(f"строка {index + 1}: нужно минимум 'действие | заголовок'")
        action, title = parts[0], parts[1]
        if not ACTION_RE.match(action):
            raise ValueError(
                f"строка {index + 1}: действие '{action}' должно быть вида "
                f"'глагол:объект', например read:crm")
        system = parts[2] if len(parts) > 2 and parts[2] else None
        try:
            cost = float(parts[3].replace(",", ".")) if len(parts) > 3 and parts[3] else 0.0
        except ValueError:
            raise ValueError(f"строка {index + 1}: цена должна быть числом") from None
        slug = re.sub(r"[^a-z0-9]+", "_", action.replace(":", "_").lower()).strip("_")
        return Step(id=f"{slug}_{index + 1}", title=title, action=action,
                    system=system, cost_kzt=cost)

    def to_line(self) -> str:
        return " | ".join([self.action, self.title, self.system or "",
                           f"{self.cost_kzt:g}" if self.cost_kzt else ""]).rstrip(" |")



@dataclass(frozen=True)
class Boundary:
    """Строка из «не делает»: заявленная граница и её исполняемый двойник.

    Граница в паспорте — это текст для человека, и закон требует именно текста
    (ст. 15, ст. 17). Но текст ничего не запрещает: шлюз проверяет типы
    действий, а не смысл фразы. «Не отправляет счета» выразимо как `send:invoice`
    и будет исполнено; «не обещает цену от имени компании» — нет, потому что это
    про содержание, а в содержание Kepil намеренно не смотрит.

    Поэтому граница может нести шаблон действия после вертикальной черты —
    как шаги профессии. Есть шаблон и он покрыт запретом мандата — граница
    исполняется. Нет — остаётся обещанием, и система обязана сказать об этом
    прямо, а не позволять принимать декларацию за механизм.
    """
    text: str
    pattern: str | None = None
    enforced: bool = False

    @staticmethod
    def parse(line: str) -> tuple[str, str | None]:
        text, _, pattern = line.partition("|")
        return text.strip(), (pattern.strip() or None)

    def to_line(self) -> str:
        return f"{self.text} | {self.pattern}" if self.pattern else self.text


@dataclass
class ProfessionDefinition:
    id: str
    name: str
    summary: str
    purpose: str
    does_not: list[str]
    intake: list[str]
    steps: list[Step]
    irreversible: list[str] = field(default_factory=lambda: ["send:*", "publish:*"])
    rollback: dict[str, str] = field(default_factory=dict)
    limits: dict[str, float] = field(default_factory=dict)
    allowed_systems: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=lambda: ["sign:*", "pay:*"])
    risk_class: str = "средний"
    risk_rationale: str = ""
    deliverable: str = ""
    human_baseline_minutes: float = 0.0
    builtin: bool = False

    # --- сериализация ---

    @staticmethod
    def from_dict(payload: dict[str, Any], builtin: bool = False) -> "ProfessionDefinition":
        data = dict(payload)
        data["steps"] = [Step(**s) for s in payload.get("steps", [])]
        data.pop("builtin", None)
        return ProfessionDefinition(**data, builtin=builtin)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("builtin", None)
        return payload

    # --- производные значения ---

    def boundaries(self) -> list[Boundary]:
        """Границы из «не делает» с пометкой, исполняется ли каждая.

        Исполняется та, у которой указан шаблон действия и этот шаблон покрыт
        запретами мандата: иначе запись обещала бы проверку, которой нет.
        """
        out: list[Boundary] = []
        for line in self.does_not:
            text, pattern = Boundary.parse(line)
            covered = bool(pattern) and any(
                _matches(pattern, f) or pattern == f for f in self.forbidden_actions)
            out.append(Boundary(text=text, pattern=pattern, enforced=covered))
        return out

    def declared_only(self) -> list[Boundary]:
        """Границы, которые остаются обещанием: их шлюз проверить не может."""
        return [b for b in self.boundaries() if not b.enforced]

    def allowed_actions(self) -> list[str]:
        seen: list[str] = []
        for step in self.steps:
            if step.action not in seen:
                seen.append(step.action)
        return seen

    def systems(self) -> list[str]:
        found = list(self.allowed_systems)
        for step in self.steps:
            if step.system and step.system not in found:
                found.append(step.system)
        return found

    def validate(self) -> list[str]:
        """Возвращает список проблем; пустой список означает «можно сохранять»."""
        problems: list[str] = []
        if not re.match(r"^[a-z][a-z0-9_]{1,30}$", self.id):
            problems.append("идентификатор: латиница в нижнем регистре, цифры и _")
        if not self.name.strip():
            problems.append("название не может быть пустым")
        if len(self.purpose.strip()) < 10:
            problems.append("назначение: минимум 10 символов, его увидит клиент в паспорте")
        if not self.does_not:
            problems.append("нужно указать хотя бы одну границу в «не делает»")
        if not self.steps:
            problems.append("нужен хотя бы один шаг")
        if self.human_baseline_minutes < 0:
            problems.append("норматив ручной работы не может быть отрицательным")
        if self.risk_class not in ("минимальный", "средний", "высокий"):
            problems.append("степень риска вне классификации ст. 17 п. 1")
        for step in self.steps:
            forbidden = [p for p in self.forbidden_actions
                         if _matches(step.action, p)]
            if forbidden:
                problems.append(
                    f"шаг «{step.title}»: действие {step.action} само себе запрещено "
                    f"правилом {forbidden[0]}")
        return problems


def _matches(action: str, pattern: str) -> bool:
    import fnmatch
    return fnmatch.fnmatch(action, pattern)


# --- реестр профессий -------------------------------------------------------

def custom_dir() -> Path:
    return data_dir() / "professions"


def load_all() -> dict[str, ProfessionDefinition]:
    """Встроенные профессии плюс созданные в админ-панели; вторые перекрывают первых."""
    found: dict[str, ProfessionDefinition] = {}
    for payload in list_json(BUILTIN_DIR):
        found[payload["id"]] = ProfessionDefinition.from_dict(payload, builtin=True)
    for payload in list_json(custom_dir()):
        found[payload["id"]] = ProfessionDefinition.from_dict(payload)
    return found


def get(profession_id: str) -> ProfessionDefinition:
    definitions = load_all()
    if profession_id not in definitions:
        raise KeyError(f"профессия '{profession_id}' не найдена")
    return definitions[profession_id]


def save(definition: ProfessionDefinition) -> None:
    problems = definition.validate()
    if problems:
        raise ValueError("; ".join(problems))
    write_json(custom_dir() / f"{definition.id}.json", definition.to_dict())


def delete(profession_id: str) -> None:
    path = custom_dir() / f"{profession_id}.json"
    if not path.exists():
        raise KeyError("удалять можно только профессии, созданные в панели")
    path.unlink()


def duplicate(profession_id: str, new_id: str, new_name: str) -> ProfessionDefinition:
    source = get(profession_id)
    payload = source.to_dict()
    payload["id"] = new_id
    payload["name"] = new_name
    copy = ProfessionDefinition.from_dict(payload)
    save(copy)
    return copy
