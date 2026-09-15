"""Паспорт: классы риска и автономности проверяются на входе."""

from datetime import date

import pytest

from kepil.professions import Profession, load
from kepil.registry import AgentPassport

OPERATOR = {"bin": "123456789012", "name": "Kepil"}
TENDER = Profession(load("tender").definition).passport(OPERATOR, released="2026-09-10")


def test_tender_passport_is_medium_autonomy():
    assert TENDER.autonomy_class == "средняя"
    assert "не подписывает документы" in TENDER.does_not


def test_high_autonomy_is_refused():
    with pytest.raises(ValueError, match="высокая автономность"):
        AgentPassport(
            agent_id="kepil.x.v1", purpose="что-то делает", does_not=["ничего"],
            created_by=OPERATOR, operated_by=OPERATOR,
            version={"agent": "1.0.0", "released_at": "2026-09-10"},
            autonomy_class="высокая",
        )


def test_unknown_risk_class_is_refused():
    with pytest.raises(ValueError, match="класс риска"):
        AgentPassport(
            agent_id="kepil.x.v1", purpose="что-то делает", does_not=["ничего"],
            created_by=OPERATOR, operated_by=OPERATOR,
            version={"agent": "1.0.0", "released_at": "2026-09-10"},
            risk_class="никакой",
        )


def test_review_due_after_a_year():
    assert TENDER.review_due(date(2027, 9, 11))
    assert not TENDER.review_due(date(2026, 12, 1))


def test_fingerprint_changes_with_content():
    before = TENDER.fingerprint()
    copy = AgentPassport(**{**TENDER.__dict__, "purpose": TENDER.purpose + "."})
    assert copy.fingerprint() != before


# --- версия -----------------------------------------------------------------

def test_version_is_not_duplicated_anywhere():
    """Номер версии живёт в pyproject, а копии расходятся с ним молча.

    Рукопожатие MCP сообщает версию наружу: устаревшая копия — это неправда,
    сказанная чужой программе.
    """
    import pathlib
    import kepil
    from kepil.mcp import server

    root = pathlib.Path(kepil.__file__).resolve().parents[2]
    declared = next(
        line.split("=", 1)[1].strip().strip('"')
        for line in (root / "pyproject.toml").read_text(encoding="utf-8").splitlines()
        if line.startswith("version"))
    assert kepil.__version__ == declared, (
        f"pyproject {declared}, пакет {kepil.__version__} — "
        "переустановите: pip install -e .")
    assert server.SERVER["version"] == declared
