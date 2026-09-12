"""Программный интерфейс: выключен без ключа, судит по мандату, пишет в журнал."""

import json

import pytest

from kepil import orders
from kepil.admin import api, app
from kepil.registry import store


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("KEPIL_DATA", str(tmp_path))
    monkeypatch.delenv("KEPIL_API_TOKEN", raising=False)
    store.save_settings({"name": "Kepil", "bin": "123456789012",
                         "operator": "оператор", "api_token": "secret-long-key-9f2"})
    yield


def request(path, method="GET", body=None, token="secret-long-key-9f2", **query):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    params = {"__json__": body} if body is not None else {}
    return app.Request(path, params, query, headers)


def call(name, method, **kwargs):
    response = app.api_call(name, method, request(f"/api/{name}", method, **kwargs))
    return response.status, json.loads(response.raw.decode("utf-8"))


# --- доступ -----------------------------------------------------------------

def test_without_a_key_the_interface_is_off():
    store.save_settings({**store.settings(), "api_token": ""})
    status, payload = call("health", "GET")
    assert status == 401
    assert "ключ" in payload["error"]


def test_wrong_key_is_refused():
    status, _ = call("health", "GET", token="wrong-key")
    assert status == 401


def test_missing_header_is_refused():
    response = app.api_call("health", "GET", app.Request("/api/health", {}, {}, {}))
    assert response.status == 401


def test_environment_key_beats_settings(monkeypatch):
    monkeypatch.setenv("KEPIL_API_TOKEN", "из-окружения")
    assert api.token() == "из-окружения"
    assert api.authorized({"authorization": "Bearer из-окружения"})
    assert not api.authorized({"authorization": "Bearer secret-long-key-9f2"})


def test_right_key_opens_the_door():
    status, payload = call("health", "GET")
    assert status == 200 and payload["ok"] is True


# --- работа -----------------------------------------------------------------

def test_professions_carry_their_boundaries():
    _, payload = call("professions", "GET")
    leads = next(p for p in payload["professions"] if p["id"] == "leads")
    assert leads["irreversible"] and leads["does_not"]


def make_order():
    _, payload = call("orders", "POST",
                      body={"profession": "leads", "client_name": "ТОО «Пример»"})
    return payload["id"]


def test_order_can_be_created_and_read():
    order_id = make_order()
    status, payload = call("order", "GET", id=order_id)
    assert status == 200
    assert payload["agent_id"] == "kepil.leads.v1"
    assert payload["mandate"]["forbidden_actions"]


def test_check_judges_by_the_mandate_without_doing_anything():
    order_id = make_order()
    _, allowed = call("check", "POST",
                      body={"order_id": order_id, "action": "read:crm",
                            "system": "crm.local"})
    assert allowed["allowed"] is True and allowed["decision"] == "allow"

    _, denied = call("check", "POST",
                     body={"order_id": order_id, "action": "read:crm",
                           "system": "evil.example.com"})
    assert denied["allowed"] is False
    assert "не разрешено" in denied["reason"]


def test_irreversible_action_answers_that_a_human_is_needed():
    order_id = make_order()
    _, payload = call("check", "POST",
                      body={"order_id": order_id, "action": "send:message",
                            "system": "whatsapp.local"})
    assert payload["needs_human"] is True
    assert payload["allowed"] is False, "разрешением это считать нельзя"


def test_every_question_lands_in_the_journal():
    order_id = make_order()
    call("check", "POST", body={"order_id": order_id, "action": "read:crm",
                                "system": "crm.local", "step": "n8n:узел-3"})
    from kepil.journal import Journal
    last = list(Journal(orders.journal_path()))[-1]
    assert last["step"] == "n8n:узел-3"
    assert last["order_id"] == order_id


def test_limits_are_spent_and_reported():
    order_id = make_order()
    _, first = call("check", "POST", body={"order_id": order_id, "action": "read:crm",
                                           "system": "crm.local", "cost_kzt": 10})
    left = first["limits_left"]["llm_cost_kzt"]
    _, second = call("check", "POST", body={"order_id": order_id, "action": "read:crm",
                                            "system": "crm.local", "cost_kzt": 10})
    assert second["limits_left"]["llm_cost_kzt"] == left - 10, "расход обязан копиться"


def test_step_moves_the_order():
    order_id = make_order()
    status, payload = call("step", "POST", id=order_id)
    assert status == 200 and payload["cursor"] == 1


def test_unknown_order_is_a_clear_404():
    status, payload = call("order", "GET", id="ord-9999")
    assert status == 404 and "не найдено" in payload["error"]


def test_journal_verification_points_at_an_independent_tool():
    make_order()
    _, payload = call("verify", "GET")
    assert payload["intact"] is True
    assert "agent-trace" in payload["independent_check"]


def test_confirmation_is_not_reachable_through_the_api():
    """Программа спрашивает разрешение, но не выдаёт его за человека."""
    names = {name for _, name in api.ROUTES}
    assert "confirm" not in names
    assert not any("confirm" in n for n in names)


def test_cyrillic_key_is_refused_at_the_form():
    """Кириллицу нельзя отправить в заголовке — ошибка должна вылезти у нас."""
    response = app.settings_save(app.Request("/settings", {
        "name": "Kepil", "bin": "123456789012", "operator": "оператор",
        "api_token": "секретный-ключ"}, {}))
    assert response.status == 200
    assert "латиницы" in response.body
    assert store.settings()["api_token"] == "secret-long-key-9f2", "старый ключ уцелел"
