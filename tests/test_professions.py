"""Профессии как описания: загрузка, разбор шагов, проверки перед сохранением."""

import pytest

from kepil.professions import Profession, ProfessionDefinition, Step, load, load_all


def test_all_builtin_professions_are_valid():
    definitions = load_all()
    assert set(definitions) >= {"leads", "automation", "primary_docs", "ai_audit", "tender"}
    for definition in definitions.values():
        assert definition.validate() == [], f"{definition.id}: {definition.validate()}"


def test_step_parses_admin_line():
    step = Step.parse("send:message | Ответ клиенту | whatsapp.local | 12,5", 3)
    assert step.action == "send:message"
    assert step.title == "Ответ клиенту"
    assert step.system == "whatsapp.local"
    assert step.cost_kzt == 12.5


def test_step_rejects_malformed_action():
    with pytest.raises(ValueError, match="глагол:объект"):
        Step.parse("отправить сообщение | Ответ", 0)


def test_step_round_trips_through_a_line():
    line = "read:crm | Проверка клиента | crm.local | 1.5"
    assert Step.parse(line, 0).to_line() == line


def test_allowed_actions_and_systems_come_from_steps():
    definition = load("leads").definition
    assert "send:message" in definition.allowed_actions()
    assert "whatsapp.local" in definition.systems()


def test_validation_catches_self_contradiction():
    definition = ProfessionDefinition(
        id="broken", name="Сломанная", summary="", purpose="Делает что-то важное",
        does_not=["ничего"], intake=["данные"],
        steps=[Step.parse("sign:document | Подписать", 0)],
        forbidden_actions=["sign:*"])
    problems = definition.validate()
    assert any("само себе запрещено" in p for p in problems)


def test_validation_requires_boundaries_and_steps():
    definition = ProfessionDefinition(
        id="empty", name="Пустая", summary="", purpose="Слишком короткое",
        does_not=[], intake=[], steps=[])
    problems = definition.validate()
    assert any("не делает" in p for p in problems)
    assert any("хотя бы один шаг" in p for p in problems)


def test_profession_passport_is_always_medium_autonomy():
    profession = Profession(load("automation").definition)
    passport = profession.passport({"bin": "123456789012", "name": "Kepil"})
    assert passport.autonomy_class == "средняя"
    assert passport.agent_id == "kepil.automation.v1"
    assert passport.risk_review["next_due"] > passport.risk_review["last"]


def test_deliver_carries_ai_marking():
    result = Profession(load("leads").definition).deliver({"id": "ord-0001"})
    assert "ст. 21" in result["ai_marking"]["visible"]
    assert result["ai_marking"]["machine_readable"]["generated_by"].startswith("kepil.")


def test_rollback_says_when_action_is_irreversible():
    profession = Profession(load("tender").definition)
    assert profession.rollback("publish:complaint") is None
    assert "отзыв" in (profession.rollback("send:package") or "")


# --- границы ----------------------------------------------------------------

def test_boundary_without_a_pattern_is_only_a_declaration():
    """Текст в «не делает» ничего не запрещает, пока нет шаблона действия."""
    from kepil.professions.definition import Boundary
    text, pattern = Boundary.parse("не обещает цену от имени компании")
    assert text == "не обещает цену от имени компании" and pattern is None


def test_boundary_with_a_pattern_is_enforced_only_if_the_mandate_forbids_it():
    """Шаблон, не покрытый запретом, — это обещание проверки, которой нет."""
    from kepil.professions import get
    definition = get("leads")
    definition.does_not = ["не шлёт счета | send:invoice",
                           "не делает чего-то ещё | do:something"]
    definition.forbidden_actions = ["send:invoice"]
    by_text = {b.text: b for b in definition.boundaries()}
    assert by_text["не шлёт счета"].enforced is True
    assert by_text["не делает чего-то ещё"].enforced is False


def test_builtin_professions_enforce_what_can_be_enforced():
    from kepil.professions import load_all
    for definition in load_all().values():
        if not definition.builtin:
            continue
        enforced = [b for b in definition.boundaries() if b.enforced]
        assert enforced, f"{definition.id}: ни одна граница не исполняется"


def test_passport_shows_the_text_without_the_pattern():
    """Паспорт читает человек: технический хвост строки туда попадать не должен."""
    from kepil.professions import Profession, get
    definition = get("leads")
    passport = Profession(definition).passport({"name": "ТОО", "bin": "123456789012"})
    assert passport.does_not
    assert not any("|" in line for line in passport.does_not)


def test_forbidden_pattern_of_a_boundary_actually_stops_the_gate(tmp_path, monkeypatch):
    """Проверка не по описанию границы, а по поведению шлюза на живом заказе."""
    monkeypatch.setenv("KEPIL_DATA", str(tmp_path))
    from kepil import orders
    from kepil.gateway import ActionGateway, ActionRequest, Decision
    from kepil.journal import Journal
    from kepil.registry import store

    store.save_settings({"name": "ТОО", "bin": "123456789012", "operator": "о"})
    definition = load("leads").definition
    bound = next(b for b in definition.boundaries() if b.enforced)

    order = orders.create("leads", {"name": "ТОО «Пример»", "bin": "987654321098"})
    gateway = ActionGateway(Journal(orders.journal_path()), lambda _: True)
    decision, reason = gateway.check(order.as_mandate(),
                                     ActionRequest(action=bound.pattern))
    assert decision is Decision.DENY, f"{bound.pattern} обязан быть отказан: {reason}"
