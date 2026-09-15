"""Чек-лист обследования и прогон по установке."""

import json

import pytest

from kepil import compliance, orders
from kepil.compliance import checklist as cl
from kepil.compliance import survey
from kepil.journal import Journal, anchor
from kepil.professions import get as get_definition
from kepil.registry import store


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("KEPIL_DATA", str(tmp_path))
    store.save_settings({"name": "ТОО Kepil", "bin": "123456789012",
                         "operator": "оператор"})
    yield


def worked_order(profession="leads"):
    order = orders.create(profession, {"name": "ТОО «Пример»", "bin": "987654321098"})
    while True:
        current = orders.get(order.id)
        if current.pending:
            orders.confirm(current, True)
            continue
        if orders.run_next(orders.get(order.id)) is None:
            break
    return orders.get(order.id)


# --- загрузка ---------------------------------------------------------------

def test_builtin_checklist_loads():
    lists = compliance.load_checklists()
    assert "generic-survey" in lists
    generic = lists["generic-survey"]
    assert generic.stages and generic.all_checks()
    assert generic.effort_days() > 0


def test_every_resolver_named_in_a_checklist_exists():
    """Пункт, ссылающийся на несуществующий резолвер, — это тихо сломанный пункт."""
    for checklist in compliance.load_checklists().values():
        for check in checklist.all_checks():
            if check.resolver:
                assert check.resolver in survey.REGISTRY, (
                    f"{checklist.id} · пункт {check.id}: нет резолвера "
                    f"«{check.resolver}»")


def test_human_checks_never_carry_a_resolver():
    """Если отвечает человек, машина не должна делать вид, что ответила."""
    for checklist in compliance.load_checklists().values():
        for check in checklist.all_checks():
            if check.answered_by == cl.BY_HUMAN:
                assert not check.resolver, f"пункт {check.id}"


def test_installed_checklist_is_picked_up(tmp_path):
    """Юрисдикция добавляется файлом, а не правкой кода."""
    directory = cl.checklists_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "demo.json").write_text(json.dumps({
        "id": "demo", "name": "Демо", "jurisdiction": "XX",
        "stages": [{"id": "1", "name": "Этап", "effort_days": 1,
                    "checks": [{"id": "1.1", "title": "Пункт",
                                "answered_by": "human"}]}],
    }, ensure_ascii=False), encoding="utf-8")
    lists = compliance.load_checklists()
    assert "demo" in lists and lists["demo"].source == "установленный"


def test_broken_file_does_not_break_loading(tmp_path):
    directory = cl.checklists_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "broken.json").write_text("{не json", encoding="utf-8")
    assert "generic-survey" in compliance.load_checklists()


# --- прогон -----------------------------------------------------------------

def test_survey_answers_what_it_can_and_admits_the_rest():
    worked_order()
    report = compliance.run_survey(compliance.get_checklist("generic-survey"))
    assert report.rows
    assert report.closed, "ни один пункт не закрыт автоматически"
    assert report.for_human, "обследование без участия человека — это неправда"
    assert 0 < report.machine_share() < 1


def test_unknown_resolver_is_reported_not_swallowed():
    check = cl.Check(id="x", title="Пункт", answered_by=cl.BY_KEPIL,
                     resolver="такого_нет")
    answer = survey._answer(check)
    assert answer.state == cl.UNKNOWN and "такого_нет" in answer.summary


def test_resolver_failure_does_not_stop_the_survey(monkeypatch):
    def explode(_):
        raise RuntimeError("сломался")
    monkeypatch.setitem(survey.REGISTRY, "risk_class_declared", explode)
    report = compliance.run_survey(compliance.get_checklist("generic-survey"))
    broken = [r for r in report.rows if r.check.resolver == "risk_class_declared"]
    assert broken and broken[0].answer.state == cl.UNKNOWN
    assert len(report.rows) == len(compliance.get_checklist("generic-survey").all_checks())


# --- отдельные резолверы ----------------------------------------------------

def test_autonomy_resolver_closes_when_high_autonomy_absent():
    worked_order()
    answer = survey.autonomy_class_declared(cl.Check(id="1.2", title=""))
    assert answer.state == cl.CLOSED and "высокой автономности нет" in answer.summary


def test_risk_review_resolver_sees_an_overdue_card(monkeypatch):
    worked_order()
    monkeypatch.setattr(store, "review_due", lambda: store.all_passports())
    answer = survey.risk_review_current(cl.Check(id="3.1", title=""))
    assert answer.state == cl.GAP and "срок пересмотра" in answer.summary


def test_journal_resolver_says_the_root_is_not_witnessed():
    """Журнал без подтверждений и якорей ничем не подпёрт снаружи.

    Заказ, дошедший только до первой остановки, ещё не создал свидетеля:
    карточка ушла, но решение не вернулось.
    """
    order = orders.create("leads", {"name": "ТОО «Пример»", "bin": "987654321098"})
    while orders.run_next(orders.get(order.id)) is not None:
        if orders.get(order.id).pending:
            break
    answer = survey.journal_intact(cl.Check(id="8.2", title=""))
    assert answer.state == cl.NEEDS_HUMAN
    assert "нигде не назван снаружи" in answer.summary


def test_journal_resolver_notes_anchors_without_signature():
    """Неподписанный якорь рядом с журналом называется в доказательствах."""
    worked_order()
    anchor(Journal(orders.journal_path()))
    answer = survey.journal_intact(cl.Check(id="8.2", title=""))
    assert any("без подписи" in line for line in answer.evidence)


def test_journal_resolver_never_closes_itself_on_its_own_evidence():
    """Пункт не закрывается перечнем, взятым из проверяемого же файла.

    Корни, названные человеку, — это шаг вперёд, но перечислять их изнутри
    журнала значит проверять только то, в чём файл сам признаётся.
    """
    worked_order()
    answer = survey.journal_intact(cl.Check(id="8.2", title=""))
    assert answer.state == cl.NEEDS_HUMAN
    assert "снаружи" in answer.summary
    assert any("названных человеку" in line for line in answer.evidence)


def test_journal_resolver_admits_when_no_head_was_ever_witnessed(monkeypatch):
    worked_order()
    monkeypatch.setattr(survey, "witnessed_heads", lambda _: [])
    answer = survey.journal_intact(cl.Check(id="8.2", title=""))
    assert answer.state == cl.NEEDS_HUMAN
    assert "обрезку" in answer.summary


def test_journal_resolver_reports_a_broken_chain():
    worked_order()
    path = orders.journal_path()
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[2] = lines[2].replace('"decision": "allow"', '"decision": "deny"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    answer = survey.journal_intact(cl.Check(id="8.2", title=""))
    assert answer.state == cl.GAP and "целостность нарушена" in answer.summary


def test_marking_resolver_catches_a_missing_half():
    """Отсутствие одной из двух форм маркировки — самостоятельное несоответствие."""
    worked_order()
    from kepil.professions import base
    monkey = lambda self, order: {"ai_marking": {"machine_readable": {"x": 1}}}
    original = base.Profession.deliver
    base.Profession.deliver = monkey
    try:
        answer = survey.marking_declared(cl.Check(id="5.2", title=""))
    finally:
        base.Profession.deliver = original
    assert answer.state == cl.GAP and "видимого предупреждения" in answer.summary


def test_suspension_resolver_closes_after_a_real_stop():
    order = worked_order()
    orders.stop(orders.get(order.id), "проверка отключения")
    answer = survey.suspension_possible(cl.Check(id="3.3", title=""))
    assert answer.state == cl.CLOSED


def test_acts_start_unverified_until_checked_against_the_source():
    """Пока акт не сверен по первоисточнику, ссылаться на него нельзя."""
    act = cl.Act.from_dict({"name": "Правила классификации", "prg_id": "34524965"})
    assert act.verified is False
    assert act.url.endswith("34524965")
