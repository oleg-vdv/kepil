# -*- coding: utf-8 -*-
"""Сквозной сценарий одного заказа: что видит оператор и что попадает в журнал.

Запуск:
    python examples/demo_order.py [путь_к_журналу]

Показывает три исхода шлюза — разрешено, отказано, ждёт человека — и то,
как результат проверяется независимо: `npx @proofbyte/agent-trace verify`.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from kepil.gateway import ActionGateway, ActionRequest, Decision
from kepil.journal import Journal, JournalEntry, verify_chain
from kepil.mandate import Mandate
from kepil.professions.tender import TenderProfession

MARK = {Decision.ALLOW: "[+]", Decision.DENY: "[x]", Decision.AWAIT_HUMAN: "[?]"}


def main(journal_path: str = "journal/demo.jsonl") -> int:
    profession = TenderProfession()
    passport = profession.passport
    now = datetime(2026, 9, 10, 12, 0)

    print("ПАСПОРТ АГЕНТА")
    print(f"  {passport.agent_id} · риск: {passport.risk_class} · "
          f"автономность: {passport.autonomy_class}")
    print(f"  назначение: {passport.purpose}")
    for line in passport.does_not:
        print(f"  не делает: {line}")
    print(f"  отпечаток: {passport.fingerprint()[:23]}…")
    print(f"  пересмотр рисков до: {passport.risk_review['next_due']}")

    mandate = Mandate(
        mandate_id="mnd-2026-09-10-0042",
        agent_id=passport.agent_id,
        order_id="ord-0042",
        principal={"bin": "987654321098", "name": "ТОО «Клиент»"},
        allowed_actions=["read:goszakup", "read:client_profile",
                         "generate:document", "send:package"],
        allowed_systems=["goszakup.gov.kz", "storage.kepil.kz"],
        forbidden_actions=["sign:*", "pay:*"],
        valid_from=now - timedelta(hours=1),
        valid_until=now + timedelta(days=7),
        human_confirmation_required=["send:*", "publish:*"],
        limits={"documents": 20, "llm_cost_kzt": 100},
    )

    print("\nМАНДАТ НА ЗАКАЗ")
    print(f"  {mandate.mandate_id} · заказ {mandate.order_id} · "
          f"от имени {mandate.principal['name']}")
    print(f"  до {mandate.valid_until:%d.%m.%Y} · лимит на модели: "
          f"{mandate.limits['llm_cost_kzt']:.0f} ₸")

    path = Path(journal_path)
    if path.exists():
        path.unlink()
    journal = Journal(path)
    gateway = ActionGateway(journal, passport_is_active=lambda _: True, now=lambda: now)

    plan = [
        ("select_announcements", ActionRequest("read:goszakup", "goszakup.gov.kz", cost_kzt=12.4)),
        ("parse_specification", ActionRequest("read:goszakup", "goszakup.gov.kz", cost_kzt=41.2)),
        ("check_eligibility", ActionRequest("read:client_profile", "storage.kepil.kz")),
        ("assemble_package", ActionRequest("generate:document", "storage.kepil.kz", cost_kzt=28.0)),
        ("sign_attempt", ActionRequest("sign:document", "storage.kepil.kz")),
        ("leak_attempt", ActionRequest("read:goszakup", "evil.example.com")),
        ("handover_to_client", ActionRequest("send:package", "storage.kepil.kz")),
        ("extra_parsing", ActionRequest("read:goszakup", "goszakup.gov.kz", cost_kzt=40.0)),
    ]

    print("\nХОД ЗАКАЗА")
    for step, request in plan:
        decision, reason = gateway.check(mandate, request)
        gateway.record(mandate, request, decision, reason, step=step)
        target = f" → {request.system}" if request.system else ""
        print(f"  {MARK[decision]} {step:22} {request.action}{target}")
        if decision is not Decision.ALLOW:
            print(f"      {reason}")

    print(f"\n  остаток лимита на модели: {mandate.remaining('llm_cost_kzt'):.1f} ₸")

    ok, err = verify_chain(journal)
    print("\nЖУРНАЛ")
    print(f"  файл: {path}")
    print(f"  записей: {sum(1 for _ in journal)} · целостность: "
          f"{'подтверждена' if ok else 'НАРУШЕНА — ' + str(err)}")
    print(f"  корень цепочки: {journal.head()[:23]}…")
    print("  подписывается ЭЦП организации и публикуется (ст. 15, ст. 21)")

    result = profession.deliver({"order_id": mandate.order_id})
    print("\nРЕЗУЛЬТАТ КЛИЕНТУ")
    print(f"  маркировка: {result['ai_marking']['visible']}")

    print("\nНЕЗАВИСИМАЯ ПРОВЕРКА")
    print(f"  npx @proofbyte/agent-trace verify {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
