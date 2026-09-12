"""Реестр выпущенных паспортов агентов.

Паспорт неизменяем: новая версия агента — новая запись, старая остаётся
навсегда. Изменить можно только статус, потому что остановка агента должна быть
мгновенной (ст. 18 п. 2), а история — нетронутой.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from ..storage import data_dir, list_json, read_json, write_json
from .passport import AgentPassport

STATUSES = {
    "active": "работает",
    "suspended": "приостановлен",
    "retired": "выведен",
}


def agents_dir() -> Path:
    return data_dir() / "agents"


def settings() -> dict[str, str]:
    stored = read_json(data_dir() / "settings.json", {}) or {}
    return {
        "bin": stored.get("bin", "000000000000"),
        "name": stored.get("name", "Kepil"),
        "operator": stored.get("operator", "оператор"),
        "telegram_token": stored.get("telegram_token", ""),
        "telegram_chat_id": stored.get("telegram_chat_id", ""),
        "api_token": stored.get("api_token", ""),
    }


def save_settings(payload: dict[str, str]) -> None:
    write_json(data_dir() / "settings.json", payload)


def all_passports() -> list[dict[str, Any]]:
    return sorted(list_json(agents_dir()), key=lambda p: p["agent_id"])


def get(agent_id: str) -> dict[str, Any] | None:
    return read_json(agents_dir() / f"{agent_id}.json")


def issue(passport: AgentPassport) -> dict[str, Any]:
    payload = asdict(passport)
    payload["passport_hash"] = passport.fingerprint()
    payload["issued_at"] = date.today().isoformat()
    write_json(agents_dir() / f"{passport.agent_id}.json", payload)
    return payload


def _major(agent_id: str) -> int:
    tail = agent_id.rsplit(".v", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def latest_for(profession_id: str) -> dict[str, Any] | None:
    """Действующий паспорт профессии — самой свежей версии."""
    candidates = [p for p in all_passports()
                  if p["agent_id"].split(".")[1] == profession_id
                  and p.get("status") == "active"]
    return max(candidates, key=lambda p: _major(p["agent_id"])) if candidates else None


def ensure_for(profession) -> dict[str, Any]:
    """Возвращает действующий паспорт профессии, выпуская его при первом заказе."""
    existing = latest_for(profession.id)
    if existing:
        return existing
    org = settings()
    return issue(profession.passport({"bin": org["bin"], "name": org["name"]}))


def reissue(agent_id: str) -> dict[str, Any]:
    """Выпускает следующую версию паспорта с текущими настройками организации.

    Паспорт неизменяем, поэтому «обновить» его нельзя: выпускается новая версия,
    предыдущая переводится в статус «выведен» и остаётся в реестре навсегда.
    Так история не теряется, а новые заказы идут на актуальные данные.
    """
    from ..professions import Profession, get as get_definition

    previous = get(agent_id)
    if previous is None:
        raise KeyError(f"паспорт '{agent_id}' не найден")

    profession_id = agent_id.split(".")[1]
    profession = Profession(get_definition(profession_id))
    org = settings()
    version = f"{_major(agent_id) + 1}.0.0"
    passport = profession.passport({"bin": org["bin"], "name": org["name"]},
                                   version=version)
    issued = issue(passport)
    set_status(agent_id, "retired")
    return issued


def set_status(agent_id: str, status: str) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"неизвестный статус: {status}")
    payload = get(agent_id)
    if payload is None:
        raise KeyError(f"паспорт '{agent_id}' не найден")
    payload["status"] = status
    write_json(agents_dir() / f"{agent_id}.json", payload)
    return payload


def is_active(agent_id: str) -> bool:
    payload = get(agent_id)
    return bool(payload and payload.get("status") == "active")


def review_due(today: date | None = None) -> list[dict[str, Any]]:
    """Паспорта, у которых подошёл срок ежегодного пересмотра рисков."""
    today = today or date.today()
    due = []
    for payload in all_passports():
        nxt = (payload.get("risk_review") or {}).get("next_due")
        if nxt and date.fromisoformat(nxt) <= today:
            due.append(payload)
    return due
