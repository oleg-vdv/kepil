"""MCP-сервер: протокол отвечает, инструменты работают, подтверждение недоступно."""

import io
import json

import pytest

from kepil import orders
from kepil.mcp import server
from kepil.registry import store


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("KEPIL_DATA", str(tmp_path))
    store.save_settings({"name": "Kepil", "bin": "123456789012", "operator": "оператор"})
    yield


def call(name, **arguments):
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                              "params": {"name": name, "arguments": arguments}})
    return response["result"]


def text(name, **arguments):
    return call(name, **arguments)["content"][0]["text"]


# --- главное ограничение ----------------------------------------------------

def test_confirmation_is_not_exposed_as_a_tool():
    """Если модель сможет подтвердить сама, человек исчезнет из цепочки."""
    names = {tool["name"] for tool in server.tool_list()}
    assert "confirm" not in names
    assert not any("confirm" in n and n != "pending_confirmations" for n in names)
    assert "pending_confirmations" in names, "смотреть очередь можно, нажимать — нет"


def test_unknown_tool_answers_without_crashing():
    result = call("approve_everything")
    assert result["isError"] is True
    assert "не найден" in result["content"][0]["text"]


# --- протокол ---------------------------------------------------------------

def test_initialize_announces_tools():
    result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"]
    assert result["serverInfo"]["name"] == "kepil"
    assert "tools" in result["capabilities"]


def test_notifications_need_no_answer():
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unsupported_method_returns_an_error():
    response = server.handle({"jsonrpc": "2.0", "id": 7, "method": "resources/list"})
    assert response["error"]["code"] == -32601


def test_every_tool_declares_a_schema():
    for tool in server.tool_list():
        assert tool["description"], tool["name"]
        assert tool["inputSchema"]["type"] == "object"
        assert "handler" not in tool, "внутренности наружу не отдаются"


def test_serve_reads_lines_and_writes_answers():
    stdin = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n")
    stdout = io.StringIO()
    server.serve(stdin, stdout)
    answer = json.loads(stdout.getvalue())
    assert any(t["name"] == "create_order" for t in answer["result"]["tools"])


def test_broken_line_does_not_kill_the_server():
    stdin = io.StringIO("не json\n" +
                        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "ping"}) + "\n")
    stdout = io.StringIO()
    server.serve(stdin, stdout)
    assert json.loads(stdout.getvalue())["id"] == 2


# --- работа -----------------------------------------------------------------

def test_professions_are_listed_with_their_boundaries():
    answer = text("list_professions")
    assert "leads" in answer
    assert "никогда не делает" in answer


def test_order_runs_through_the_same_gate():
    created = text("create_order", profession="leads", client_name="Клиника «Пример»")
    order_id = created.split()[2]

    seen = [text("run_step", order_id=order_id) for _ in range(5)]
    assert any("выполнено" in line for line in seen)
    assert any("ждёт" in line for line in seen), "необратимое обязано остановиться"

    assert order_id in text("pending_confirmations")
    assert "дёт подтверждения человека" in text("order_status", order_id=order_id)


def test_journal_stays_verifiable_after_mcp_work():
    created = text("create_order", profession="tender", client_name="ТОО «Пример»")
    order_id = created.split()[2]
    text("run_step", order_id=order_id)
    assert "подтверждена" in text("verify_journal")


def test_passport_is_readable_and_missing_one_is_explained():
    created = text("create_order", profession="leads", client_name="ТОО")
    order = orders.get(created.split()[2])
    assert "kepil.leads" in text("agent_passport", agent_id=order.agent_id)
    assert "не найден" in text("agent_passport", agent_id="kepil.nope.v9")
