"""MCP-сервер: Kepil внутри чужих инструментов.

Любой клиент Model Context Protocol — редактор, ассистент, чужой агент — может
подключить Kepil и работать через него: посмотреть доступные профессии, создать
заказ, выполнить шаг, проверить целостность журнала. Действия при этом проходят
через тот же шлюз и попадают в тот же журнал, что и в панели.

Одного инструмента здесь намеренно нет: **подтверждения**.

Если бы модель могла вызвать «подтвердить», человек исчез бы из цепочки —
агент сам себе разрешал бы необратимое действие, и весь смысл системы
испарился. Поэтому карточка подтверждения уходит человеку в панель или в
Telegram, и никакой клиент MCP её нажать не может.

Протокол: JSON-RPC 2.0 поверх стандартного ввода-вывода, только стандартная
библиотека.

    python -m kepil.mcp
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable

from .. import orders
from ..gateway import Decision
from ..professions import load_all
from ..registry import store as agents

PROTOCOL = "2025-06-18"
SERVER = {"name": "kepil", "version": "0.2.0"}


# --- инструменты ------------------------------------------------------------

def _list_professions() -> str:
    lines = []
    for definition in load_all().values():
        lines.append(
            f"{definition.id} — {definition.name}: {definition.summary or definition.purpose}\n"
            f"  шагов: {len(definition.steps)}; "
            f"требуют человека: {', '.join(definition.irreversible)}; "
            f"никогда не делает: {'; '.join(definition.does_not)}")
    return "\n".join(lines) or "профессии не найдены"


def _create_order(profession: str, client_name: str, client_bin: str = "",
                  days: int = 7) -> str:
    order = orders.create(profession,
                          {"name": client_name, "bin": client_bin or "000000000000"},
                          days=int(days))
    steps = order.definition().steps
    return (f"Создан заказ {order.id} · агент {order.agent_id}\n"
            f"Мандат {order.mandate['mandate_id']} действует до "
            f"{order.mandate['valid_until'][:10]}\n"
            f"Шагов впереди: {len(steps)}. Необратимые действия потребуют "
            f"подтверждения человеком — подтвердить отсюда нельзя.")


def _run_step(order_id: str) -> str:
    order = orders.get(order_id)
    result = orders.run_next(order)
    if result is None:
        order = orders.get(order_id)
        if order.pending:
            return (f"Заказ {order_id} остановлен: шаг «{order.pending['title']}» "
                    f"ждёт подтверждения человека в панели или в Telegram.")
        return f"Заказ {order_id}: шагов больше нет, статус «{order.status}»."
    decision, reason = result
    order = orders.get(order_id)
    mark = {Decision.ALLOW: "выполнено", Decision.DENY: "отказано",
            Decision.AWAIT_HUMAN: "ждёт человека"}[decision]
    return (f"Заказ {order_id}, шаг {order.cursor} из {len(order.definition().steps)}: "
            f"{mark}. Основание: {reason}")


def _order_status(order_id: str) -> str:
    order = orders.get(order_id)
    done = [r for r in order.results if r["decision"] == "allow"]
    denied = [r for r in order.results if r["decision"] == "deny"]
    lines = [f"Заказ {order.id} · {order.client.get('name', '')} · статус {order.status}",
             f"Профессия: {order.definition().name}",
             f"Шагов пройдено: {order.cursor} из {len(order.definition().steps)}; "
             f"выполнено {len(done)}, отклонено {len(denied)}"]
    if order.pending:
        lines.append(f"Ждёт подтверждения человека: {order.pending['title']} "
                     f"({order.pending['action']})")
    for row in denied:
        lines.append(f"  отказ на «{row['title']}»: {row['reason']}")
    return "\n".join(lines)


def _pending() -> str:
    waiting = [o for o in orders.list_orders() if o.status == "awaiting"]
    if not waiting:
        return "Ничего не ждёт подтверждения."
    return "\n".join(
        f"{o.id} · {o.client.get('name', '')} · {o.pending['title']} "
        f"({o.pending['action']} → {o.pending.get('system') or '—'})" for o in waiting)


def _verify_journal() -> str:
    ok, error = orders.verify_journal()
    if ok:
        return ("Целостность журнала подтверждена. Независимая проверка: "
                "npx proofbyte-agent-trace verify <путь к journal.jsonl>")
    return f"Целостность НАРУШЕНА: {error}"


def _passport(agent_id: str) -> str:
    payload = agents.get(agent_id)
    if payload is None:
        return f"Паспорт «{agent_id}» не найден."
    return json.dumps(payload, ensure_ascii=False, indent=2)


TOOLS: list[dict[str, Any]] = [
    {"name": "list_professions",
     "description": "Что агенты умеют делать: профессии, их шаги и границы.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": lambda **_: _list_professions()},
    {"name": "create_order",
     "description": "Создать заказ на профессию: выдаётся паспорт агента и мандат на срок.",
     "inputSchema": {"type": "object",
                     "properties": {"profession": {"type": "string"},
                                    "client_name": {"type": "string"},
                                    "client_bin": {"type": "string"},
                                    "days": {"type": "integer"}},
                     "required": ["profession", "client_name"]},
     "handler": lambda **kw: _create_order(**kw)},
    {"name": "run_step",
     "description": "Выполнить следующий шаг заказа через шлюз. "
                    "Необратимое действие остановится и будет ждать человека.",
     "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}},
                     "required": ["order_id"]},
     "handler": lambda **kw: _run_step(**kw)},
    {"name": "order_status",
     "description": "Состояние заказа: пройденные шаги, отказы и их причины.",
     "inputSchema": {"type": "object", "properties": {"order_id": {"type": "string"}},
                     "required": ["order_id"]},
     "handler": lambda **kw: _order_status(**kw)},
    {"name": "pending_confirmations",
     "description": "Что сейчас ждёт решения человека. Подтвердить отсюда нельзя — "
                    "только посмотреть.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": lambda **_: _pending()},
    {"name": "verify_journal",
     "description": "Проверить целостность журнала действий.",
     "inputSchema": {"type": "object", "properties": {}},
     "handler": lambda **_: _verify_journal()},
    {"name": "agent_passport",
     "description": "Паспорт агента: назначение, границы, классы риска и автономности.",
     "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}},
                     "required": ["agent_id"]},
     "handler": lambda **kw: _passport(**kw)},
]

BY_NAME: dict[str, Callable[..., str]] = {t["name"]: t["handler"] for t in TOOLS}


def tool_list() -> list[dict[str, Any]]:
    return [{k: v for k, v in tool.items() if k != "handler"} for tool in TOOLS]


# --- протокол ---------------------------------------------------------------

def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    """Обрабатывает одно сообщение. None означает «ответа не требуется»."""
    method = message.get("method")
    request_id = message.get("id")

    if method == "initialize":
        return _ok(request_id, {"protocolVersion": PROTOCOL,
                                "capabilities": {"tools": {}},
                                "serverInfo": SERVER})
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _ok(request_id, {})
    if method == "tools/list":
        return _ok(request_id, {"tools": tool_list()})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name", "")
        handler = BY_NAME.get(name)
        if handler is None:
            return _ok(request_id, _text(f"Инструмент «{name}» не найден.", error=True))
        try:
            text = handler(**(params.get("arguments") or {}))
            return _ok(request_id, _text(text))
        except KeyError as exc:
            return _ok(request_id, _text(f"Не найдено: {exc}", error=True))
        except Exception as exc:                       # сбой инструмента не роняет сервер
            return _ok(request_id, _text(f"Ошибка: {exc!r}", error=True))

    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32601, "message": f"метод «{method}» не поддерживается"}}


def _ok(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _text(text: str, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def serve(stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
