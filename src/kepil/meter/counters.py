"""Подсчёт по журналу.

Один проход по записям даёт всё: сколько действий сделано, сколько отклонено,
сколько раз потребовался человек, во что обошлись обращения к моделям и сколько
человеческого времени заменено.

Замещённое время считается честно: норматив ручной работы берётся из описания
профессии (сколько занимает тот же заказ у человека), из него вычитается время,
которое человек всё-таки потратил на подтверждения. Если норматив не заполнен,
строка так и остаётся пустой — выдумывать экономию нельзя.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ..journal import Journal
from ..orders.service import journal_path, list_orders
from ..professions import load_all

MINUTES_PER_CONFIRMATION = 2.0


@dataclass
class Counters:
    actions: int = 0
    allowed: int = 0
    denied: int = 0
    awaited: int = 0
    confirmations: int = 0
    returns: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_kzt: float = 0.0
    human_minutes: float = 0.0
    baseline_minutes: float = 0.0
    orders_done: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def saved_minutes(self) -> float | None:
        """Замещённое время. None, если норматив ручной работы не заполнен."""
        if not self.baseline_minutes:
            return None
        return max(0.0, self.baseline_minutes - self.human_minutes)

    @property
    def cost_per_action(self) -> float:
        return self.cost_kzt / self.actions if self.actions else 0.0

    @property
    def autonomy_share(self) -> float:
        """Доля действий, прошедших без участия человека."""
        return self.allowed / self.actions if self.actions else 0.0

    def add_record(self, record: dict[str, Any]) -> None:
        self.actions += 1
        decision = record.get("decision")
        if decision == "allow":
            self.allowed += 1
        elif decision == "deny":
            self.denied += 1
        elif decision == "await_human":
            self.awaited += 1

        human = record.get("human")
        if human:
            self.human_minutes += MINUTES_PER_CONFIRMATION
            if human.get("approved"):
                self.confirmations += 1
            else:
                self.returns += 1

        model = record.get("model") or {}
        self.tokens_in += int(model.get("tokens_in") or 0)
        self.tokens_out += int(model.get("tokens_out") or 0)
        self.cost_kzt += float(record.get("cost_kzt") or 0.0)


def _records() -> Iterable[dict[str, Any]]:
    return Journal(journal_path())


def _baseline(profession_id: str) -> float:
    definition = load_all().get(profession_id)
    return float(getattr(definition, "human_baseline_minutes", 0.0) or 0.0)


def for_order(order_id: str) -> Counters:
    counters = Counters()
    for record in _records():
        if record.get("order_id") == order_id:
            counters.add_record(record)
    order = next((o for o in list_orders() if o.id == order_id), None)
    if order is not None:
        counters.baseline_minutes = _baseline(order.profession)
        counters.orders_done = 1 if order.status == "done" else 0
        if not counters.baseline_minutes:
            counters.notes.append(
                "норматив ручной работы не заполнен в профессии — "
                "замещённое время не считается")
    return counters


def totals() -> Counters:
    counters = Counters()
    for record in _records():
        counters.add_record(record)
    for order in list_orders():
        if order.status == "done":
            counters.orders_done += 1
            counters.baseline_minutes += _baseline(order.profession)
    return counters


def _grouped(key: str) -> dict[str, Counters]:
    order_index = {o.id: o for o in list_orders()}
    groups: dict[str, Counters] = {}
    for record in _records():
        order = order_index.get(record.get("order_id", ""))
        name = (record.get("agent_id", "—") if key == "agent"
                else (order.profession if order else "—"))
        groups.setdefault(name, Counters()).add_record(record)
    for order in order_index.values():
        if order.status != "done":
            continue
        name = order.agent_id if key == "agent" else order.profession
        if name in groups:
            groups[name].orders_done += 1
            groups[name].baseline_minutes += _baseline(order.profession)
    return dict(sorted(groups.items()))


def by_agent() -> dict[str, Counters]:
    return _grouped("agent")


def by_profession() -> dict[str, Counters]:
    return _grouped("profession")
