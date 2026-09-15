"""JSON-интерфейс: Kepil как страж для чужих автоматизаций.

Панель предназначена человеку, а этот слой — программам. Через него n8n, Make,
собственный скрипт или чужой агент спрашивают одно и то же: **можно ли это
действие** — и получают ответ вместе с записью в журнале.

Две вещи устроены намеренно строго.

Первая: без заданного ключа интерфейс выключен целиком. Панель на localhost
защищена тем, что слушает только localhost, а программный доступ так защитить
нельзя — значит по умолчанию его нет.

Вторая: подтверждение необратимых действий сюда не вынесено, как и в
MCP-сервере. Программа может спросить разрешение и получить ответ «нужен
человек», но выдать это разрешение за человека — не может.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..gateway import ActionGateway, ActionRequest, Decision
from ..journal import Journal
from ..orders import service as orders
from ..professions import definition as professions
from ..registry import store as agents


def token() -> str:
    """Ключ доступа: переменная окружения важнее сохранённых настроек."""
    return (os.environ.get("KEPIL_API_TOKEN")
            or agents.settings().get("api_token", "")).strip()


def authorized(headers: dict[str, str]) -> bool:
    expected = token()
    if not expected:
        return False
    given = (headers.get("authorization") or "").strip()
    if given.lower().startswith("bearer "):
        given = given[7:].strip()
    return bool(given) and given == expected


# --- обработчики ------------------------------------------------------------

def health() -> dict[str, Any]:
    ok, error = orders.verify_journal()
    return {"ok": True, "journal": {"intact": ok, "problem": error},
            "professions": len(professions.load_all()),
            "orders": len(orders.list_orders())}


def list_professions() -> dict[str, Any]:
    return {"professions": [
        {"id": d.id, "name": d.name, "steps": len(d.steps),
         "irreversible": d.irreversible,
         "does_not": [{"text": b.text, "pattern": b.pattern,
                       "enforced": b.enforced} for b in d.boundaries()],
         "limits": d.limits}
        for d in professions.load_all().values()]}


def create_order(payload: dict[str, Any]) -> dict[str, Any]:
    order = orders.create(
        payload["profession"],
        {"name": payload.get("client_name", "—"),
         "bin": payload.get("client_bin", "000000000000")},
        days=int(payload.get("days", 7)))
    return order_view(order.id)


def order_view(order_id: str) -> dict[str, Any]:
    order = orders.get(order_id)
    return {
        "id": order.id, "status": order.status, "agent_id": order.agent_id,
        "profession": order.profession, "client": order.client,
        "cursor": order.cursor, "steps": len(order.definition().steps),
        "mandate": {k: order.mandate[k] for k in
                    ("mandate_id", "allowed_actions", "forbidden_actions",
                     "allowed_systems", "human_confirmation_required",
                     "limits", "valid_until")},
        "pending": order.pending,
        "results": order.results,
    }


def run_step(order_id: str) -> dict[str, Any]:
    result = orders.run_next(orders.get(order_id))
    view = order_view(order_id)
    if result is None:
        view["decision"] = None
        view["reason"] = ("ждёт подтверждения человека" if view["pending"]
                          else "шагов больше нет")
    else:
        decision, reason = result
        view["decision"] = decision.value
        view["reason"] = reason
    return view


def check_action(payload: dict[str, Any]) -> dict[str, Any]:
    """Спросить разрешение на действие, не выполняя его.

    Ответ «allow» не выполняет действие — его делает вызывающая сторона. Смысл
    в том, что решение принято шлюзом по мандату и попало в журнал: потом можно
    доказать, на каком основании автоматизация это сделала.
    """
    order = orders.get(payload["order_id"])
    mandate = order.as_mandate()
    request = ActionRequest(
        action=payload["action"],
        system=payload.get("system"),
        payload_ref=payload.get("payload_ref"),
        cost_kzt=float(payload.get("cost_kzt", 0) or 0),
        amount_kzt=float(payload.get("amount_kzt", 0) or 0))

    gateway = ActionGateway(Journal(orders.journal_path()), agents.is_active)
    decision, reason = gateway.check(mandate, request)
    gateway.record(mandate, request, decision, reason,
                   step=payload.get("step", "external:check"))
    order.store_mandate(mandate)
    order.save()

    return {
        "decision": decision.value,
        "allowed": decision is Decision.ALLOW,
        "needs_human": decision is Decision.AWAIT_HUMAN,
        "reason": reason,
        "order_id": order.id,
        "mandate_id": order.mandate["mandate_id"],
        "limits_left": {k: mandate.remaining(k) for k in mandate.limits},
    }


def verify_journal() -> dict[str, Any]:
    ok, error = orders.verify_journal()
    records = sum(1 for _ in Journal(orders.journal_path()))
    return {"intact": ok, "problem": error, "records": records,
            "independent_check": "npx proofbyte-agent-trace verify <journal.jsonl>"}


# --- маршрутизация ----------------------------------------------------------

ROUTES: dict[tuple[str, str], Any] = {
    ("GET", "health"): lambda body, query: health(),
    ("GET", "professions"): lambda body, query: list_professions(),
    ("POST", "orders"): lambda body, query: create_order(body),
    ("GET", "order"): lambda body, query: order_view(query["id"]),
    ("POST", "step"): lambda body, query: run_step(query["id"]),
    ("POST", "check"): lambda body, query: check_action(body),
    ("GET", "verify"): lambda body, query: verify_journal(),
}


def handle(name: str, method: str, body: dict[str, Any],
           query: dict[str, str]) -> tuple[int, dict[str, Any]]:
    handler = ROUTES.get((method, name))
    if handler is None:
        return 404, {"error": f"нет обработчика для {method} {name}"}
    try:
        return 200, handler(body, query)
    except KeyError as exc:
        return 404, {"error": f"не найдено: {exc}"}
    except ValueError as exc:
        return 400, {"error": str(exc)}
    except Exception as exc:                       # сбой не должен ронять сервер
        return 500, {"error": repr(exc)}


def dumps(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
