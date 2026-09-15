"""Заказы и панель: шлюз останавливает необратимое, панель отвечает на маршрутах."""

import pytest

from kepil import orders
from kepil.admin import app
from kepil.admin.app import Request, resolve
from kepil.gateway import Decision
from kepil.professions import load
from kepil.registry import store


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Каждый тест работает в своём каталоге данных."""
    monkeypatch.setenv("KEPIL_DATA", str(tmp_path))
    store.save_settings({"name": "Kepil", "bin": "123456789012", "operator": "оператор"})
    yield


def make_order(profession="leads"):
    return orders.create(profession, {"name": "ТОО «Пример»", "bin": "987654321098"})


def run_until_stop(order_id):
    """Крутит шаги, пока агент не упрётся в человека или не кончатся шаги."""
    while orders.run_next(orders.get(order_id)) is not None:
        if orders.get(order_id).pending:
            break
    return orders.get(order_id)


def test_order_issues_passport_and_mandate():
    order = make_order()
    assert order.agent_id == "kepil.leads.v1"
    assert store.is_active(order.agent_id)
    assert order.mandate["forbidden_actions"]
    assert order.mandate["valid_until"] > order.mandate["valid_from"]


def test_agent_stops_before_irreversible_action():
    order = run_until_stop(make_order().id)
    assert order.status == "awaiting"
    assert order.pending["action"].startswith("send:")
    assert orders.verify_journal()[0]


def test_confirmation_is_recorded_with_the_person():
    order = run_until_stop(make_order().id)
    orders.confirm(order, True, "")
    entries = [r for r in _journal() if r.get("human")]
    assert entries and entries[-1]["human"]["approved"] is True
    assert entries[-1]["decision"] == "allow"


def test_return_with_note_is_recorded_as_denial():
    order = run_until_stop(make_order().id)
    orders.confirm(order, False, "цена неверная")
    last = [r for r in _journal() if r.get("human")][-1]
    assert last["decision"] == "deny"
    assert last["human"]["note"] == "цена неверная"


def test_suspended_agent_stops_working():
    order = make_order()
    store.set_status(order.agent_id, "suspended")
    decision, reason = orders.run_next(orders.get(order.id))
    assert decision is Decision.DENY
    assert "неактивен" in reason


def test_cost_limit_stops_the_order():
    definition = load("leads").definition
    order = orders.create("leads", {"name": "ТОО", "bin": "987654321098"},
                          limits={"llm_cost_kzt": 3.0})
    orders.run_next(orders.get(order.id))          # шаг за 2 ₸ проходит
    decision, reason = orders.run_next(orders.get(order.id))
    assert decision is Decision.DENY and "исчерпан" in reason
    assert definition.limits["llm_cost_kzt"] > 3.0  # исходное описание не тронуто


def test_journal_survives_a_full_order():
    order = run_until_stop(make_order("tender").id)
    ok, err = orders.verify_journal()
    assert ok, err
    assert all(r["order_id"] == order.id for r in _journal())


def _journal():
    from kepil.journal import Journal
    return list(Journal(orders.journal_path()))


# --- панель -----------------------------------------------------------------

@pytest.mark.parametrize("method,path,expected_id", [
    ("GET", "/", None),
    ("GET", "/orders", None),
    ("GET", "/orders/ord-0001", "ord-0001"),
    ("POST", "/orders/ord-0001/confirm", "ord-0001"),
    ("GET", "/professions/leads", "leads"),
    ("POST", "/professions/leads/delete", "leads"),
    ("POST", "/agents/kepil.leads.v1/status", "kepil.leads.v1"),
])
def test_routes_resolve(method, path, expected_id):
    found = resolve(method, path)
    assert found is not None, f"{method} {path}"
    assert found[1].get("id") == expected_id


def test_unknown_route_is_not_resolved():
    assert resolve("GET", "/nope") is None
    assert resolve("POST", "/orders") is None


def test_form_helpers_parse_admin_input():
    request = Request("/x", {"lines": "первая\n\n вторая ",
                             "pairs": "documents = 20\nllm_cost_kzt = 3000"}, {})
    assert request.lines("lines") == ["первая", "вторая"]
    assert request.pairs("pairs") == {"documents": "20", "llm_cost_kzt": "3000"}


def test_admin_pages_render():
    from kepil.admin import app
    make_order()
    for handler in (app.overview, app.orders_list, app.professions_list,
                    app.agents_list, app.journal_view, app.settings_view):
        response = handler(Request("/", {}, {}))
        assert response.status == 200
        assert "Kepil" in response.body


def test_reissue_creates_a_new_version_and_retires_the_old():
    order = make_order()
    store.save_settings({"name": "ТОО «Настоящее»", "bin": "210987654321",
                         "operator": "Олег"})
    issued = store.reissue(order.agent_id)

    assert issued["agent_id"] == "kepil.leads.v2"
    assert issued["operated_by"]["bin"] == "210987654321"
    assert store.get(order.agent_id)["status"] == "retired"
    assert store.latest_for("leads")["agent_id"] == "kepil.leads.v2"


def test_new_orders_go_to_the_latest_passport():
    make_order()
    store.reissue("kepil.leads.v1")
    assert make_order().agent_id == "kepil.leads.v2"


def test_old_orders_keep_their_agent():
    old = make_order()
    store.reissue(old.agent_id)
    assert orders.get(old.id).agent_id == "kepil.leads.v1"


# --- устойчивость -----------------------------------------------------------

def test_damaged_journal_line_is_reported_not_swallowed():
    """Битая строка — это поломка целостности, а не отсутствие данных.

    Пропустить её молча нельзя: за ней может прятаться удалённая запись.
    """
    from kepil.journal import Journal, verify_chain
    run_until_stop(make_order().id)
    path = orders.journal_path()
    path.write_text(path.read_text(encoding="utf-8") + "это не json\n", encoding="utf-8")

    journal = Journal(path)                    # объект обязан создаться
    assert journal.damaged() == [len(path.read_text(encoding="utf-8").splitlines())]
    ok, problem = verify_chain(journal)
    assert not ok and "повреждён" in problem
    assert journal.records(), "читаемые записи должны остаться доступными"


def test_damaged_journal_does_not_break_the_panel():
    run_until_stop(make_order().id)
    path = orders.journal_path()
    path.write_text(path.read_text(encoding="utf-8") + "{обрыв\n", encoding="utf-8")
    response = app.journal_view(Request("/journal", {}, {}))
    assert response.status == 200
    ok, problem = orders.verify_journal()
    assert not ok and problem


def test_profession_in_use_cannot_be_deleted():
    """Удалённое описание профессии делает журнал по её заказам необъяснимым."""
    from kepil.professions import duplicate, save
    copy = duplicate("leads", "leads_copy", "Заявки (копия)")
    save(copy)
    orders.create("leads_copy", {"name": "ТОО «Пример»", "bin": "987654321098"})

    response = app.profession_delete(Request("/x", {}, {"id": "leads_copy"}))
    assert "нельзя удалить" in response.body
    from kepil.professions import get as get_definition
    assert get_definition("leads_copy"), "профессия должна остаться на месте"


def test_unused_profession_can_be_deleted():
    from kepil.professions import duplicate, save, get as get_definition
    copy = duplicate("leads", "leads_spare", "Заявки (запас)")
    save(copy)
    app.profession_delete(Request("/x", {}, {"id": "leads_spare"}))
    with pytest.raises(KeyError):
        get_definition("leads_spare")
