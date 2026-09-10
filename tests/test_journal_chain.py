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
