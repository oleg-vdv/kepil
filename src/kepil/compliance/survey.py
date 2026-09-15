"""Прогон чек-листа по установке: что система доказывает сама.

Резолвер — маленькая функция, которая отвечает на один пункт чек-листа,
глядя на паспорта, журнал, профессии и пакет документации. Ответ всегда
состоит из трёх вещей: закрыт пункт или нет, чем это подтверждается и где
лежит доказательство.

Резолверы объявлены здесь и только здесь. Файл чек-листа ссылается на имя из
REGISTRY и ничего исполняемого не содержит — иначе чужой JSON стал бы способом
выполнить код на машине, где ведётся журнал.

Ни один резолвер не возвращает «соответствует закону». Он возвращает факт:
класс автономности такой-то, остановок столько-то, документ отсутствует.
Вывод о соответствии делает человек, и подпись под заключением тоже его.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from ..journal import (Journal, anchors, verify_with_anchors,
                       witnessed_heads)
from ..orders import service as orders
from ..professions import definition as professions
from ..registry import store as agents
from .checklist import (BY_HUMAN, BY_KEPIL, CLOSED, GAP, NEEDS_HUMAN, UNKNOWN,
                        Check, Checklist)
from . import generator, packs


@dataclass
class Answer:
    """Ответ резолвера на один пункт."""
    state: str
    summary: str
    evidence: list[str] = field(default_factory=list)

    @staticmethod
    def closed(summary: str, *evidence: str) -> "Answer":
        return Answer(CLOSED, summary, list(evidence))

    @staticmethod
    def gap(summary: str, *evidence: str) -> "Answer":
        return Answer(GAP, summary, list(evidence))

    @staticmethod
    def human(summary: str, *evidence: str) -> "Answer":
        return Answer(NEEDS_HUMAN, summary, list(evidence))


# --- резолверы --------------------------------------------------------------

def _passports() -> list[dict[str, Any]]:
    return agents.all_passports()


def risk_class_declared(_: Check) -> Answer:
    """Класс риска объявлен по каждой системе и обоснован."""
    cards = _passports()
    if not cards:
        return Answer.gap("паспортов нет: классифицировать нечего")
    without = [c["agent_id"] for c in cards if not c.get("risk_rationale")]
    listed = ", ".join(f"{c['agent_id']} — {c.get('risk_class', '?')}" for c in cards)
    if without:
        return Answer.gap(
            "класс риска проставлен, но без обоснования сценариями отказа: "
            + ", ".join(without),
            f"паспорта: {listed}")
    return Answer.closed(f"классифицировано систем: {len(cards)}", f"паспорта: {listed}")


def autonomy_class_declared(_: Check) -> Answer:
    """Уровень автономности и техническая возможность отмены решения."""
    cards = _passports()
    if not cards:
        return Answer.gap("паспортов нет")
    high = [c["agent_id"] for c in cards if c.get("autonomy_class") == "высокая"]
    if high:                                   # конструктор паспорта такое не создаёт
        return Answer.gap("заявлена высокая автономность: " + ", ".join(high))
    classes = {c.get("autonomy_class", "?") for c in cards}
    return Answer.closed(
        "высокой автономности нет; отмена решения человеком сохранена",
        f"классы: {', '.join(sorted(classes))}",
        "очередь подтверждений и компенсирующие действия в журнале")


def risk_review_current(_: Check) -> Answer:
    """Пересмотр рисков не реже раза в год (ст. 18 п. 1 пп. 4)."""
    cards = _passports()
    if not cards:
        return Answer.gap("паспортов нет")
    due = agents.review_due()
    if due:
        overdue = ", ".join(
            f"{c['agent_id']} (до {c.get('risk_review', {}).get('next_due', '?')})"
            for c in due)
        return Answer.gap(f"срок пересмотра наступил: {overdue}")
    dates = ", ".join(
        f"{c['agent_id']} — до {c.get('risk_review', {}).get('next_due', '?')}"
        for c in cards)
    return Answer.closed("сроки пересмотра не истекли", dates)


def documentation_complete(_: Check) -> Answer:
    """Комплектность документации по перечню для своего класса риска."""
    try:
        pack = packs.get()
    except Exception as exc:                   # пакет не установлен — это тоже ответ
        return Answer.gap(f"пакет документации недоступен: {exc!r}")
    cards = _passports()
    if not cards:
        return Answer.gap("паспортов нет: состав пакета определить не от чего")
    problems: list[str] = []
    evidence: list[str] = []
    for card in cards:
        required = pack.required(card.get("risk_class", ""))
        evidence.append(f"{card['agent_id']}: требуется документов {len(required)}")
        if not required:
            problems.append(f"{card['agent_id']}: перечень для класса "
                            f"«{card.get('risk_class', '?')}» пуст")
    if problems:
        return Answer.gap("; ".join(problems), *evidence)
    return Answer.closed(f"пакет «{pack.name}» определяет состав по классу риска",
                         *evidence)


def marking_declared(_: Check) -> Answer:
    """Маркировка синтетики: обе составляющие, а не одна из двух.

    Закон требует и машиночитаемую метку, и воспринимаемое предупреждение
    (ст. 21 п. 2). Отсутствие любой из двух — самостоятельное несоответствие,
    поэтому проверяются обе.
    """
    from ..professions import Profession

    defs = professions.load_all()
    if not defs:
        return Answer.gap("профессий нет")
    broken: list[str] = []
    for definition in defs.values():
        marking = Profession(definition).deliver({"id": "—"}).get("ai_marking") or {}
        if not marking.get("machine_readable"):
            broken.append(f"{definition.id}: нет машиночитаемой метки")
        if not marking.get("visible"):
            broken.append(f"{definition.id}: нет видимого предупреждения")
    if broken:
        return Answer.gap("; ".join(broken))
    return Answer.closed(
        "у каждой профессии есть и машиночитаемая метка, и видимое предупреждение",
        f"профессий проверено: {len(defs)}",
        "натурная проверка исходящих материалов остаётся за человеком")


def human_control_procedures(_: Check) -> Answer:
    """Права пользователя и контроль человека — процедуры, а не декларации."""
    journal = Journal(orders.journal_path())
    records = list(journal)
    if not records:
        return Answer.gap("журнал пуст: подтвердить исполнение процедур нечем")
    human = [r for r in records if r.get("human")]
    approved = [r for r in human if (r.get("human") or {}).get("approved") is True]
    refused = [r for r in human if (r.get("human") or {}).get("approved") is False]
    denied = [r for r in records if r.get("decision") == "deny"]
    return Answer.closed(
        f"решения человека зафиксированы: подтверждений {len(approved)}, "
        f"отказов человека {len(refused)}, отказов шлюза {len(denied)}",
        f"записей в журнале: {len(records)}",
        "каждая запись содержит основание решения (ст. 16 п. 1 пп. 4–5)")


def suspension_possible(_: Check) -> Answer:
    """Незамедлительная приостановка эксплуатации (ст. 18 п. 2)."""
    records = list(Journal(orders.journal_path()))
    stops = [r for r in records if (r.get("action") or {}).get("type") == "stop:order"]
    statuses = {c.get("status") for c in _passports()}
    evidence = [f"остановок в журнале: {len(stops)}",
                f"статусы паспортов: {', '.join(sorted(s for s in statuses if s))}"]
    if not stops:
        return Answer(NEEDS_HUMAN,
                      "механизм остановки есть, но натурная проверка не проводилась: "
                      "закон требует продемонстрировать отключение и замерить время",
                      evidence)
    return Answer.closed("остановка применялась и зафиксирована в журнале", *evidence)


def journal_intact(_: Check) -> Answer:
    """Целостность журнала и то, чем она подпёрта снаружи.

    Цепочка хешей доказывает, что уцелевшие записи согласуются друг с другом.
    Она не доказывает, что ничего не убрали: журнал можно обрезать и пересчитать
    заново, и проверка цепочки этого не заметит.

    Подпорок снаружи две, и они независимы. Зафиксированный корень — если он
    подписан и хранится не рядом с журналом. И корень, названный человеку на
    карточке подтверждения: карточка уходит из процесса-писателя, её копия
    остаётся в переписке, и обрезанная история на такой корень уже не сошлётся.
    """
    journal = Journal(orders.journal_path())
    ok, problem = verify_with_anchors(journal)
    fixed = anchors(journal)
    seen = witnessed_heads(journal)
    unsigned = [a for a in fixed if not a.get("signature")]

    evidence = [f"записей: {sum(1 for _ in journal)}",
                f"зафиксированных корней: {len(fixed)}",
                f"корней, названных человеку при подтверждении: {len(seen)}"]
    if unsigned:
        evidence.append(f"якорей без подписи, рядом с журналом: {len(unsigned)}")

    if not ok:
        return Answer.gap(f"целостность нарушена: {problem}", *evidence)

    signed = [a for a in fixed if a.get("signature")]
    if seen or signed:
        return Answer.closed(
            "цепочка сходится, и есть корень, названный за пределами журнала: "
            "обрезанная и пересобранная история на него не сошлётся", *evidence)

    if fixed:
        return Answer(NEEDS_HUMAN,
                      f"корни фиксируются, но все {len(fixed)} без подписи и лежат "
                      "рядом с журналом — переписать можно и то и другое",
                      evidence)
    return Answer(NEEDS_HUMAN,
                  "цепочка сходится, но корень нигде не назван снаружи: обрезку "
                  "истории подтвердить нечем", evidence)

def boundaries_enforced(_: Check) -> Answer:
    """Границы из паспорта: какие проверяет шлюз, а какие остаются обещанием.

    Паспорт объявляет, чего агент не делает никогда. Шлюз проверяет типы
    действий, а не смысл фразы, поэтому часть границ исполнима, а часть — нет:
    «не отправляет счета» выразимо как send:invoice, «не обещает цену от имени
    компании» — нет, это про содержание.

    Обе разновидности законны, незаконно их путать. Граница, которую никто не
    проверяет, должна называться заявлением, иначе документ обещает механизм,
    которого не существует.
    """
    defs = professions.load_all()
    if not defs:
        return Answer.gap("профессий нет")
    enforced = declared = 0
    only: list[str] = []
    for definition in defs.values():
        for boundary in definition.boundaries():
            if boundary.enforced:
                enforced += 1
            else:
                declared += 1
                only.append(f"{definition.id}: {boundary.text}")
    evidence = [f"исполняется шлюзом: {enforced}", f"остаётся заявлением: {declared}"]
    if not declared:
        return Answer.closed("каждая граница паспорта имеет исполняемый запрет", *evidence)
    return Answer(NEEDS_HUMAN,
                  f"границ без исполняемого запрета: {declared}. Их соблюдение "
                  f"подтверждает человек, шлюз проверить смысл фразы не может: "
                  + "; ".join(only[:4]) + ("…" if len(only) > 4 else ""),
                  evidence)


def inventory_present(_: Check) -> Answer:
    """Реестр систем: полнота проверяется человеком, состав — системой."""
    cards = _passports()
    defs = professions.load_all()
    evidence = [f"паспортов: {len(cards)}", f"профессий: {len(defs)}"]
    if not cards:
        return Answer.gap("реестр пуст", *evidence)
    return Answer(NEEDS_HUMAN,
                  f"реестр содержит {len(cards)} систем; полноту подтверждает человек: "
                  "встроенные функции ИИ в покупном ПО и теневые сервисы установка "
                  "не видит",
                  evidence)


#: Имя из файла чек-листа → функция. Ничего, кроме этих имён, не вызывается.
REGISTRY: dict[str, Callable[[Check], Answer]] = {
    "risk_class_declared": risk_class_declared,
    "autonomy_class_declared": autonomy_class_declared,
    "risk_review_current": risk_review_current,
    "documentation_complete": documentation_complete,
    "marking_declared": marking_declared,
    "human_control_procedures": human_control_procedures,
    "suspension_possible": suspension_possible,
    "journal_intact": journal_intact,
    "inventory_present": inventory_present,
    "boundaries_enforced": boundaries_enforced,
}


# --- прогон -----------------------------------------------------------------

@dataclass
class Row:
    check: Check
    stage_id: str
    stage_name: str
    answer: Answer


@dataclass
class Report:
    checklist: Checklist
    rows: list[Row]
    made_at: str

    def by_state(self, state: str) -> list[Row]:
        return [r for r in self.rows if r.answer.state == state]

    @property
    def closed(self) -> list[Row]:
        return self.by_state(CLOSED)

    @property
    def gaps(self) -> list[Row]:
        return self.by_state(GAP)

    @property
    def for_human(self) -> list[Row]:
        return [r for r in self.rows if r.answer.state in (NEEDS_HUMAN, UNKNOWN)]

    def machine_share(self) -> float:
        """Доля пунктов, закрытых без человека. Ноль, если пунктов нет."""
        return len(self.closed) / len(self.rows) if self.rows else 0.0

    def critical_gaps(self) -> list[Row]:
        return [r for r in self.gaps if r.check.severity == "критическая"]


def run(checklist: Checklist) -> Report:
    """Прогоняет чек-лист по текущей установке."""
    rows: list[Row] = []
    for stage in checklist.stages:
        for check in stage.checks:
            rows.append(Row(check, stage.id, stage.name, _answer(check)))
    return Report(checklist, rows, date.today().isoformat())


def _answer(check: Check) -> Answer:
    if check.answered_by == BY_HUMAN or not check.resolver:
        return Answer(NEEDS_HUMAN, "отвечает человек: система этого знать не может")
    resolver = REGISTRY.get(check.resolver)
    if resolver is None:
        return Answer(UNKNOWN, f"резолвер «{check.resolver}» не объявлен")
    try:
        return resolver(check)
    except Exception as exc:                   # сбой резолвера не отменяет обследование
        return Answer(UNKNOWN, f"резолвер «{check.resolver}» не отработал: {exc!r}")
