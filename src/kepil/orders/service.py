"""Жизненный цикл заказа.

Заказ — единица работы: клиент, профессия, мандат на срок и последовательность
шагов. Шаги выполняет агент, но каждое действие проходит через шлюз, а всё
необратимое останавливается и ждёт человека.

Состояние хранится в JSON-файлах: заказ можно открыть, прочитать и приложить к
спору. Журнал общий для установки и только дописывается.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from ..gateway import ActionGateway, ActionRequest, Decision
from ..journal import Journal, JournalEntry, verify_chain
from ..mandate import Mandate
from ..professions import Profession, get as get_definition
from ..registry import store as agents
from ..storage import data_dir, list_json, next_id, read_json, write_json

TZ = "+05:00"
STATUSES = {
    "new": "новый",
    "running": "в работе",
    "awaiting": "ждёт подтверждения",
    "done": "готов",
    "stopped": "остановлен",
}


def orders_dir() -> Path:
    return data_dir() / "orders"


def journal_path() -> Path:
    return data_dir() / "journal.jsonl"


@dataclass
class Order:
    id: str
    profession: str
    client: dict[str, str]
    agent_id: str
    mandate: dict[str, Any]
    created_at: str
    status: str = "new"
    cursor: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    pending: dict[str, Any] | None = None
    note: str = ""

    # --- сохранение ---

    @staticmethod
    def load(order_id: str) -> "Order":
        payload = read_json(orders_dir() / f"{order_id}.json")
        if payload is None:
            raise KeyError(f"заказ '{order_id}' не найден")
        return Order(**payload)

    def save(self) -> None:
        write_json(orders_dir() / f"{self.id}.json", asdict(self))

    # --- производные ---

    def definition(self):
        return get_definition(self.profession)

    def profession_obj(self) -> Profession:
        return Profession(self.definition())

    def as_mandate(self) -> Mandate:
        payload = dict(self.mandate)
        payload["valid_from"] = datetime.fromisoformat(payload["valid_from"])
        payload["valid_until"] = datetime.fromisoformat(payload["valid_until"])
        spent = payload.pop("spent", {})
        mandate = Mandate(**payload)
        mandate._spent = dict(spent)
        return mandate

    def store_mandate(self, mandate: Mandate) -> None:
        self.mandate = {
            "mandate_id": mandate.mandate_id,
            "agent_id": mandate.agent_id,
            "order_id": mandate.order_id,
            "principal": mandate.principal,
            "allowed_actions": mandate.allowed_actions,
            "allowed_systems": mandate.allowed_systems,
            "forbidden_actions": mandate.forbidden_actions,
            "human_confirmation_required": mandate.human_confirmation_required,
            "limits": mandate.limits,
            "valid_from": mandate.valid_from.isoformat(),
            "valid_until": mandate.valid_until.isoformat(),
            "spent": mandate._spent,
        }

    def steps_view(self) -> list[dict[str, Any]]:
        """Шаги профессии вместе с их исходом — то, что видно в панели."""
        done = {row["step"]: row for row in self.results}
        view = []
        for index, step in enumerate(self.definition().steps):
            row = done.get(step.id)
            view.append({
                "index": index,
                "step": step,
                "decision": row["decision"] if row else None,
                "reason": row["reason"] if row else "",
                "at": row.get("at", "") if row else "",
            })
        return view

    def spent(self, key: str) -> float:
        return float(self.mandate.get("spent", {}).get(key, 0.0))


# --- операции ---------------------------------------------------------------

def create(profession_id: str, client: dict[str, str], days: int = 7,
           limits: dict[str, float] | None = None) -> Order:
    """Создаёт заказ и выдаёт мандат на срок его выполнения."""
    definition = get_definition(profession_id)
    profession = Profession(definition)
    existing = [o["id"] for o in list_json(orders_dir())]
    order_id = next_id("ord", existing)

    passport = agents.ensure_for(profession)
    now = datetime.now()
    mandate = Mandate(
        mandate_id=order_id.replace("ord", "mnd"),
        agent_id=passport["agent_id"],
        order_id=order_id,
        principal=client,
        allowed_actions=definition.allowed_actions(),
        allowed_systems=definition.systems(),
        forbidden_actions=list(definition.forbidden_actions),
        human_confirmation_required=list(definition.irreversible),
        limits=dict(limits or definition.limits),
        valid_from=now,
        valid_until=now + timedelta(days=days),
    )
    order = Order(
        id=order_id,
        profession=profession_id,
        client=client,
        agent_id=passport["agent_id"],
        mandate={},
        created_at=now.isoformat(timespec="seconds"),
    )
    order.store_mandate(mandate)
    order.save()
    return order


def get(order_id: str) -> Order:
    return Order.load(order_id)


def list_orders() -> list[Order]:
    return sorted((Order(**payload) for payload in list_json(orders_dir())),
                  key=lambda o: o.id, reverse=True)


def _gateway() -> ActionGateway:
    return ActionGateway(
        Journal(journal_path()),
        passport_is_active=agents.is_active,
    )


def run_next(order: Order) -> tuple[Decision, str] | None:
    """Выполняет следующий шаг. Возвращает None, если выполнять нечего."""
    steps = order.definition().steps
    if order.pending or order.cursor >= len(steps):
        return None

    step = steps[order.cursor]
    mandate = order.as_mandate()
    gateway = _gateway()
    request = ActionRequest(action=step.action, system=step.system,
                            cost_kzt=step.cost_kzt)
    decision, reason = gateway.check(mandate, request)
    gateway.record(mandate, request, decision, reason, step=step.id)

    row = {"step": step.id, "title": step.title, "action": step.action,
           "system": step.system, "cost_kzt": step.cost_kzt,
           "decision": decision.value, "reason": reason,
           "at": datetime.now().isoformat(timespec="seconds")}
    order.results.append(row)
    order.cursor += 1
    order.store_mandate(mandate)

    if decision is Decision.AWAIT_HUMAN:
        order.pending = row
        order.status = "awaiting"
    elif order.cursor >= len(steps):
        order.status = "done"
    else:
        order.status = "running"
    order.save()
    return decision, reason


def confirm(order: Order, approved: bool, note: str = "") -> None:
    """Решение человека по действию из очереди подтверждений."""
    if not order.pending:
        return
    row = order.pending
    row["decision"] = Decision.ALLOW.value if approved else Decision.DENY.value
    row["reason"] = ("подтверждено оператором" if approved
                     else f"возвращено оператором: {note or 'без пояснения'}")
    for saved in order.results:
        if saved["step"] == row["step"]:
            saved.update(row)

    Journal(journal_path()).append(JournalEntry(
        agent_id=order.agent_id,
        order_id=order.id,
        mandate_id=order.mandate["mandate_id"],
        step=f"{row['step']}:human",
        action={"type": row["action"], "target": row["system"]},
        decision=row["decision"],
        human={"required": True, "approved": approved,
               "confirmed_by": "operator", "note": note,
               "at": datetime.now().isoformat(timespec="seconds")},
    ))
    order.pending = None
    order.status = "done" if order.cursor >= len(order.definition().steps) else "running"
    order.save()


def verify_journal() -> tuple[bool, str | None]:
    return verify_chain(Journal(journal_path()))
