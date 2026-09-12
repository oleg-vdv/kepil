"""Счётчик, комплаенс, остановка с откатом и фиксация корня журнала."""

import json

import pytest

from kepil import compliance, meter, orders
from kepil.journal import Journal, anchor, anchors, verify_with_anchors
from kepil.professions import get as get_definition
from kepil.registry import store


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("KEPIL_DATA", str(tmp_path))
    store.save_settings({"name": "ТОО Kepil", "bin": "123456789012",
                         "operator": "оператор"})
    yield


def order_until_stop(profession="leads"):
    order = orders.create(profession, {"name": "ТОО «Пример»", "bin": "987654321098"})
    while orders.run_next(orders.get(order.id)) is not None:
        if orders.get(order.id).pending:
            break
    return orders.get(order.id)


# --- счётчик ----------------------------------------------------------------

def test_meter_counts_actions_and_cost():
    order = order_until_stop()
    counters = meter.for_order(order.id)
    assert counters.actions == len(order.results)
    assert counters.cost_kzt > 0
    assert 0 < counters.autonomy_share <= 1


def test_meter_counts_human_decisions_separately():
    order = order_until_stop()
    orders.confirm(order, False, "цена неверная")
    counters = meter.for_order(order.id)
    assert counters.returns == 1
    assert counters.confirmations == 0
    assert counters.human_minutes > 0


def test_saved_time_needs_a_norm():
    order = order_until_stop()
    while orders.run_next(orders.get(order.id)) is not None:
        current = orders.get(order.id)
        if current.pending:
            orders.confirm(current, True)
    counters = meter.for_order(order.id)
    assert counters.saved_minutes is not None  # у профессии норматив заполнен

    empty = meter.Counters()
    assert empty.saved_minutes is None, "без норматива экономию выдумывать нельзя"


def test_meter_groups_by_profession_and_agent():
    order_until_stop("leads")
    order_until_stop("tender")
    assert set(meter.by_profession()) == {"leads", "tender"}
    assert set(meter.by_agent()) == {"kepil.leads.v1", "kepil.tender.v1"}


# --- комплаенс --------------------------------------------------------------

def _passport(profession="leads"):
    """Паспорт появляется вместе с первым заказом профессии."""
    return store.get(order_until_stop(profession).agent_id)


def _documents(profession="leads"):
    order = order_until_stop(profession)
    passport = store.get(order.agent_id)
    definition = get_definition(profession)
    return compliance.build(definition, passport, store.settings(),
                            {"actions": 4, "denied": 0, "journal_ok": True})


def test_medium_risk_requires_three_documents():
    documents = _documents()
    required = [d.key for d in documents if d.required]
    assert required == ["system", "risk", "data"]


def test_high_risk_adds_the_policy():
    order = order_until_stop("leads")
    passport = store.get(order.agent_id)
    passport["risk_class"] = "высокий"
    documents = compliance.build(get_definition("leads"), passport, store.settings())
    assert "policy" in [d.key for d in documents if d.required]


def test_documents_carry_real_data_not_placeholders():
    documents = {d.key: d.body for d in _documents()}
    assert "kepil.leads.v1" in documents["system"]
    assert "ТОО Kepil" in documents["system"]
    assert "Приём входящей заявки" in documents["system"], "шаги профессии подставлены"
    assert "не выгружает базу клиентов" in documents["system"], "границы подставлены"
    assert "приостанавливается немедленно" in documents["risk"]


def test_marking_document_contains_both_forms():
    body = {d.key: d.body for d in _documents()}["marking"]
    assert '"ai_generated": true' in body, "машиночитаемая метка"
    assert "искусственного интеллекта" in body, "видимое предупреждение"


# --- пакеты документации ----------------------------------------------------

def test_builtin_pack_is_jurisdiction_neutral():
    """Открытая часть не должна тянуть за собой чужое законодательство."""
    for document in _documents():
        assert "230-VIII" not in document.body
        assert "95/НҚ" not in document.body


def test_installed_pack_is_picked_up(tmp_path, monkeypatch):
    """Пакет под законодательство кладётся файлом и подхватывается без кода."""
    from kepil.compliance import installed_dir
    from kepil.compliance.packs import load_all

    directory = installed_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "demo-law.json").write_text(json.dumps({
        "id": "demo-law", "name": "Демо-юрисдикция",
        "required_by_risk": {"средний": ["rule"]},
        "documents": [{"key": "rule", "title": "Документ по статье 42",
                       "sections": [{"heading": "Основание",
                                     "blocks": ["Система {agent_id} соответствует статье 42.",
                                                "@boundaries"]}]}],
    }, ensure_ascii=False), encoding="utf-8")

    assert "demo-law" in load_all()
    documents = compliance.build(get_definition("leads"), _passport(),
                                 store.settings(), {}, "demo-law")
    assert len(documents) == 1
    assert "статье 42" in documents[0].body
    assert "kepil.leads.v1" in documents[0].body
    assert "не подписывает" in documents[0].body or "не выгружает" in documents[0].body


def test_unknown_pack_falls_back_to_builtin():
    documents = compliance.build(get_definition("leads"), _passport(),
                                 store.settings(), {}, "нет-такого-пакета")
    assert [d.key for d in documents] == [d.key for d in _documents()]


def test_gaps_are_marked_for_a_human():
    documents = _documents()
    assert compliance.missing_marks(documents) > 0, (
        "документ без пометок означает, что система выдумала недостающее")


# --- остановка и откат ------------------------------------------------------

def test_stop_clears_the_queue_and_is_recorded():
    order = order_until_stop()
    orders.stop(order, "клиент отозвал заявку")
    order = orders.get(order.id)
    assert order.status == "stopped" and order.pending is None
    last = list(Journal(orders.journal_path()))[-1]
    assert last["action"]["type"] == "stop:order"
    assert last["human"]["note"] == "клиент отозвал заявку"


def test_resume_returns_the_order_to_work():
    order = order_until_stop()
    orders.stop(order, "пауза")
    orders.resume(orders.get(order.id))
    assert orders.get(order.id).status == "running"


def test_rollback_uses_the_compensation_from_the_profession():
    order = order_until_stop()
    step = order.results[0]["step"]
    done, message = orders.rollback(order, step)
    assert done and message
    assert list(Journal(orders.journal_path()))[-1]["step"].endswith(":rollback")


def test_rollback_refuses_when_action_is_irreversible():
    order = order_until_stop("tender")
    while orders.run_next(orders.get(order.id)) is not None:
        current = orders.get(order.id)
        if current.pending:
            orders.confirm(current, True)
    order = orders.get(order.id)
    definition = get_definition("tender")
    definition.rollback["read:goszakup"] = ""      # объявляем шаг необратимым
    from kepil.professions import save as save_profession
    save_profession(definition)
    done, message = orders.rollback(order, order.results[0]["step"])
    assert not done and "необратимо" in message


def test_rollback_happens_once():
    order = order_until_stop()
    step = order.results[0]["step"]
    orders.rollback(order, step)
    done, message = orders.rollback(orders.get(order.id), step)
    assert not done and "уже откачен" in message


# --- якоря ------------------------------------------------------------------

def test_anchor_fixes_the_head():
    order_until_stop()
    journal = Journal(orders.journal_path())
    record = anchor(journal)
    assert record["head"] == journal.head()
    assert anchors(journal)[-1]["seq"] == record["seq"]


def test_empty_journal_cannot_be_anchored(tmp_path):
    with pytest.raises(ValueError, match="пуст"):
        anchor(Journal(tmp_path / "empty.jsonl"))


def test_rewritten_journal_is_caught_by_the_anchor():
    order_until_stop()
    path = orders.journal_path()
    journal = Journal(path)
    anchor(journal)

    # переписываем журнал целиком и пересчитываем все хеши — цепочка сойдётся
    from kepil.journal import JournalEntry
    path.unlink()
    fresh = Journal(path)
    fresh.append(JournalEntry(agent_id="kepil.leads.v1",
                              action={"type": "read:inbox"}, decision="allow"))

    ok, error = verify_with_anchors(fresh)
    assert not ok and "якорь" in error
