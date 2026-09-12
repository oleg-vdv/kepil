"""Сборка комплекта документации на систему искусственного интеллекта.

Документы собираются из того, что система знает о себе: паспорта агента,
описания профессии и журнала действий. Это принципиально: комплаенс, набранный
руками в текстовом редакторе, расходится с реальностью на второй неделе, а
собранный из журнала — не может.

Тексты живут отдельно от движка (см. packs.py). Здесь только подстановка
значений и разворачивание директив вида `@steps` в таблицы и списки.

Ничего не выдумывается: там, где данных нет, в документе остаётся явная
пометка о том, что заполняет человек.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..professions.definition import ProfessionDefinition
from .packs import Pack, get as get_pack, load_all as load_packs

TODO = "**Заполняет человек:** "
DIRECTIVE = re.compile(r"^@(\w+)$")


@dataclass
class Document:
    key: str
    title: str
    filename: str
    body: str
    required: bool


# --- подстановки ------------------------------------------------------------

def _values(definition: ProfessionDefinition, passport: dict[str, Any],
            org: dict[str, str], stats: dict[str, Any]) -> dict[str, str]:
    review = passport.get("risk_review") or {}
    version = passport.get("version") or {}
    return {
        "agent_id": passport.get("agent_id", "—"),
        "org_name": org.get("name", "—"),
        "org_bin": org.get("bin", "—"),
        "operator": org.get("operator", "—"),
        "version": version.get("agent", "—"),
        "released": version.get("released_at", "—"),
        "date": date.today().isoformat(),
        "passport_hash": passport.get("passport_hash", "—"),
        "risk_class": passport.get("risk_class", "—"),
        "autonomy_class": passport.get("autonomy_class", "—"),
        "purpose": definition.purpose,
        "summary": definition.summary or TODO + "краткое описание области применения.",
        "risk_rationale": definition.risk_rationale or TODO + "обоснование классификации.",
        "deliverable": definition.deliverable or "—",
        "review_last": review.get("last", "—"),
        "review_next": review.get("next_due", "—"),
        "actions": str(stats.get("actions", 0)),
        "denied": str(stats.get("denied", 0)),
        "confirmations": str(stats.get("confirmations", 0)),
        "returns": str(stats.get("returns", 0)),
        "journal": "подтверждена" if stats.get("journal_ok") else "ТРЕБУЕТ ПРОВЕРКИ",
        "todo": TODO,
    }


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- не заданы"


def _code_bullets(items: list[str]) -> str:
    return "\n".join(f"- `{item}`" for item in items) if items else "- не заданы"


def _directive(name: str, definition: ProfessionDefinition) -> str:
    if name == "steps":
        rows = "\n".join(
            f"| {i + 1} | {s.title} | `{s.action}` | {s.system or '—'} |"
            for i, s in enumerate(definition.steps))
        return ("| № | Шаг | Действие | Внешняя система |\n|---|---|---|---|\n" + rows
                if rows else "Шаги не заданы.")
    if name == "boundaries":
        return _bullets(definition.does_not)
    if name == "intake":
        return _bullets(definition.intake)
    if name == "irreversible":
        return _code_bullets(definition.irreversible)
    if name == "forbidden":
        return _code_bullets(definition.forbidden_actions)
    if name == "limits":
        return ("\n".join(f"- `{k}` — не более {v:g}" for k, v in definition.limits.items())
                if definition.limits else TODO + "лимиты не заданы в описании профессии.")
    if name == "systems":
        return _code_bullets(definition.systems())
    return f"(неизвестная директива @{name})"


def _render_block(block: str, values: dict[str, str],
                  definition: ProfessionDefinition) -> str:
    match = DIRECTIVE.match(block.strip())
    if match:
        return _directive(match.group(1), definition)
    try:
        return block.format(**values)
    except (KeyError, IndexError, ValueError):
        return block           # текст с фигурными скобками не должен ломать сборку


def _header(title: str, values: dict[str, str]) -> list[str]:
    return [
        f"# {title}", "",
        f"**Система:** {values['agent_id']}  ",
        f"**Владелец системы:** {values['org_name']}, БИН {values['org_bin']}  ",
        f"**Версия агента:** {values['version']} от {values['released']}  ",
        f"**Дата документа:** {values['date']}  ",
        f"**Отпечаток паспорта:** `{values['passport_hash']}`", "",
    ]


# --- сборка -----------------------------------------------------------------

def build(definition: ProfessionDefinition, passport: dict[str, Any],
          org: dict[str, str], stats: dict[str, Any] | None = None,
          pack_id: str | None = None) -> list[Document]:
    """Комплект для одной версии агента по выбранному пакету документации."""
    pack: Pack = get_pack(pack_id)
    values = _values(definition, passport, org, stats or {})
    required = pack.required(passport.get("risk_class", "средний"))

    documents: list[Document] = []
    for spec in pack.documents:
        lines = _header(spec["title"].format(**values), values)
        for section in spec.get("sections", []):
            heading = section.get("heading")
            if heading:
                lines += [f"## {heading.format(**values)}", ""]
            for block in section.get("blocks", []):
                lines += [_render_block(block, values, definition), ""]
        documents.append(Document(
            key=spec["key"],
            title=spec["title"].format(**values),
            filename=f"{values['agent_id']}-{spec['key']}.md",
            body="\n".join(lines).rstrip() + "\n",
            required=spec["key"] in required,
        ))
    return documents


def missing_marks(documents: list[Document]) -> int:
    """Сколько мест в комплекте ждут человека."""
    return sum(doc.body.count(TODO) for doc in documents)


def available_packs() -> dict[str, Pack]:
    return load_packs()
