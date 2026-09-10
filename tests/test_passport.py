"""Паспорт: классы риска и автономности проверяются на входе."""

from datetime import date

import pytest

from kepil.registry import AgentPassport
from kepil.professions.tender import PASSPORT as TENDER


def test_tender_passport_is_medium_autonomy():
    assert TENDER.autonomy_class == "средняя"
    assert "не подписывает документы" in TENDER.does_not


def test_high_autonomy_is_refused():
    with pytest.raises(ValueError, match="высокая автономность"):
        AgentPassport(
            agent_id="kepil.x.v1", purpose="что-то делает", does_not=["ничего"],
            created_by={"bin": "000000000000"}, operated_by={"bin": "000000000000"},
            version={"agent": "1.0.0", "released_at": "2026-09-10"},
            autonomy_class="высокая",
        )


def test_unknown_risk_class_is_refused():
    with pytest.raises(ValueError, match="класс риска"):
        AgentPassport(
            agent_id="kepil.x.v1", purpose="что-то делает", does_not=["ничего"],
            created_by={"bin": "000000000000"}, operated_by={"bin": "000000000000"},
            version={"agent": "1.0.0", "released_at": "2026-09-10"},
            risk_class="никакой",
        )


def test_review_due_after_a_year():
    assert TENDER.review_due(date(2027, 9, 10))
    assert not TENDER.review_due(date(2026, 12, 1))


def test_fingerprint_changes_with_content():
    before = TENDER.fingerprint()
    copy = AgentPassport(**{**TENDER.__dict__, "purpose": TENDER.purpose + "."})
    assert copy.fingerprint() != before
