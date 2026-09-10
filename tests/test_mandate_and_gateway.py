"""Мандат и шлюз: без явного разрешения — отказ; необратимое — к человеку."""

from datetime import datetime, timedelta

import pytest

from kepil.gateway import ActionGateway, ActionRequest, Decision
from kepil.journal import Journal
from kepil.mandate import Mandate, MandateError


def make_mandate(**over):
    now = datetime(2026, 9, 10, 12, 0)
    base = dict(
        mandate_id="mnd-1", agent_id="kepil.tender.v1", order_id="ord-1",
        principal={"bin": "987654321098"},
        allowed_actions=["read:goszakup", "generate:document", "send:package"],
        allowed_systems=["goszakup.gov.kz", "storage.kepil.kz"],
        forbidden_actions=["sign:*", "pay:*"],
        valid_from=now - timedelta(hours=1),
        valid_until=now + timedelta(days=7),
        human_confirmation_required=["send:*", "publish:*"],
        limits={"documents": 20, "llm_cost_kzt": 3000},
    )
    base.update(over)
    return Mandate(**base)


def gateway(tmp_path, active=True):
    return ActionGateway(
        Journal(tmp_path / "journal.jsonl"),
        passport_is_active=lambda _: active,
        now=lambda: datetime(2026, 9, 10, 12, 0),
    )


def test_allowed_action_passes(tmp_path):
    decision, _ = gateway(tmp_path).check(
        make_mandate(), ActionRequest("read:goszakup", "goszakup.gov.kz"))
    assert decision is Decision.ALLOW


def test_unlisted_action_is_denied(tmp_path):
    decision, reason = gateway(tmp_path).check(
        make_mandate(), ActionRequest("delete:contract"))
    assert decision is Decision.DENY
    assert "не разрешено" in reason


def test_forbidden_beats_allowed(tmp_path):
    m = make_mandate(allowed_actions=["sign:document"])
    decision, _ = gateway(tmp_path).check(m, ActionRequest("sign:document"))
    assert decision is Decision.DENY


def test_foreign_system_is_denied(tmp_path):
    decision, _ = gateway(tmp_path).check(
        make_mandate(), ActionRequest("read:goszakup", "evil.example.com"))
    assert decision is Decision.DENY


def test_irreversible_goes_to_human(tmp_path):
    decision, _ = gateway(tmp_path).check(
        make_mandate(), ActionRequest("send:package", "storage.kepil.kz"))
    assert decision is Decision.AWAIT_HUMAN


def test_expired_mandate_is_denied(tmp_path):
    m = make_mandate(valid_until=datetime(2026, 9, 9))
    decision, reason = gateway(tmp_path).check(m, ActionRequest("read:goszakup"))
    assert decision is Decision.DENY
    assert "сроку" in reason


def test_inactive_passport_blocks_everything(tmp_path):
    decision, _ = gateway(tmp_path, active=False).check(
        make_mandate(), ActionRequest("read:goszakup", "goszakup.gov.kz"))
    assert decision is Decision.DENY


def test_cost_limit_is_enforced(tmp_path):
    g, m = gateway(tmp_path), make_mandate(limits={"llm_cost_kzt": 100})
    assert g.check(m, ActionRequest("read:goszakup", cost_kzt=90))[0] is Decision.ALLOW
    decision, reason = g.check(m, ActionRequest("read:goszakup", cost_kzt=20))
    assert decision is Decision.DENY
    assert "исчерпан" in reason


def test_unknown_limit_is_rejected():
    with pytest.raises(MandateError):
        make_mandate(limits={}).spend("amount_kzt", 1)
