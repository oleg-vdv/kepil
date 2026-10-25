"""Журнал: цепочка неразрывна, подделка обнаруживается."""

import json

from kepil.journal import Journal, JournalEntry, verify_chain


def _entry(action="read:goszakup", decision="allow"):
    return JournalEntry(agent_id="kepil.tender.v1",
                        action={"type": action},
                        decision=decision)


def test_chain_is_valid_after_appends(tmp_path):
    j = Journal(tmp_path / "journal.jsonl")
    for _ in range(5):
        j.append(_entry())
    ok, err = verify_chain(j)
    assert ok, err


def test_tampering_is_detected(tmp_path):
    path = tmp_path / "journal.jsonl"
    j = Journal(path)
    for _ in range(3):
        j.append(_entry())

    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["decision"] = "deny"          # правим прошлое
    lines[1] = json.dumps(record, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, err = verify_chain(Journal(path))
    assert not ok
    assert "изменено" in err


def test_head_moves_forward(tmp_path):
    j = Journal(tmp_path / "journal.jsonl")
    first = j.append(_entry())
    second = j.append(_entry())
    assert second["prev_hash"] == first["hash"]
    assert j.head() == second["hash"]


def test_canonical_numbers_are_javascript_compatible(tmp_path):
    """Целые float пишутся как int — иначе внешний верификатор на JS не сойдётся."""
    from kepil.journal.chain import _canonical

    assert b'"cost_kzt":0' in _canonical({"cost_kzt": 0.0})
    assert b'"cost_kzt":41.2' in _canonical({"cost_kzt": 41.2})
    assert b'"n":1' in _canonical({"n": 1})
    assert b'"flag":true' in _canonical({"flag": True})
    assert b'"nested":{"x":3}' in _canonical({"nested": {"x": 3.0}})


def test_canonical_numbers_follow_ecmascript_formatting():
    """Python и JavaScript по-разному пишут малые, большие и экспоненциальные числа.

    Стоимость шага в 0.00005 ₸ раньше давала в Python "5e-05", и журнал
    объявлялся подделанным внешним верификатором.
    """
    from kepil.journal.chain import _es_number

    cases = {
        5e-05: "0.00005", 1.5e-07: "1.5e-7", 1e-07: "1e-7", 1e-06: "0.000001",
        1e21: "1e+21", 1e20: "100000000000000000000", 1.2345678901234568e+20:
        "123456789012345680000", 123.456: "123.456", -0.5: "-0.5",
        1792918806.4002304: "1792918806.4002304", 0.1 + 0.2: "0.30000000000000004",
        2.5e-300: "2.5e-300", 1.7976931348623157e308: "1.7976931348623157e+308",
    }
    for value, expected in cases.items():
        assert _es_number(value) == expected, value
