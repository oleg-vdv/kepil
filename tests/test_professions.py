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
