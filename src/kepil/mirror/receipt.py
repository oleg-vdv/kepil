"""Расписка о выданной карточке: доказательство в руках получателя.

Укреплять зеркало бесполезно: любой вариант «хранить копию понадёжнее»
заканчивается стороной, которая может хранилище удалить. Дальше расстояние
растёт, а устройство не меняется.

Меняет устройство другое — когда карточка несёт доказательство на себе.
Получатель держит расписку; обнаружение перестаёт зависеть от перечисления
чьего-либо ящика. Достаточно одного предъявителя: подпись сходится, корня в
журнале нет, расхождение существует. Расписка доказывает, что карточка была
выдана, и ничего не говорит о том, почему записи нет, — это и не её дело.

Подписывать своим ключом не получается: асимметричной подписи в стандартной
библиотеке нет, а HMAC не годится — тот, кто держит ключ для проверки, сможет
изготовить расписку сам, и она перестанет что-либо доказывать.

Но почта уже подписана. Исходящее письмо подписывает отправляющий сервер по
DKIM, ключ для проверки лежит в DNS домена — в месте, которым писатель журнала
не распоряжается. Пересланная копия остаётся проверяемой, когда переслана
вложением: пересылка в теле письма ломает хеш тела. Условие одно: заголовок
`X-Kepil-Head` должен входить в список подписанных, иначе подпись покрывает
письмо, но не корень.

Здесь расписка разбирается и проверяется её **покрытие**: назван ли корень,
есть ли подпись, входит ли заголовок с корнем в подписанное. Сверка самой
подписи не делается и делается не здесь — для неё нужен ключ из DNS и разбор
RSA. Модуль говорит, что именно осталось непроверенным, вместо того чтобы
молча выдать «подтверждено».
"""

from __future__ import annotations

import email
import email.policy
import re
from typing import Any

HEAD_HEADER = "X-Kepil-Head"
REF_HEADER = "X-Kepil-Ref"
HEAD_RE = re.compile(r"sha256:[0-9a-f]{64}")


def read_receipt(raw: bytes | str) -> dict[str, Any]:
    """Разбирает пересланную карточку и описывает, что в ней доказано.

    Возвращает и корень, и состояние подписи. Ни одно поле не означает
    «проверено»: проверка подписи требует ключа из DNS и здесь не делается.
    """
    message = email.message_from_bytes(
        raw if isinstance(raw, bytes) else raw.encode("utf-8"),
        policy=email.policy.default)

    head = (message.get(HEAD_HEADER) or "").strip()
    if not head:
        body = _plain_text(message)
        found = HEAD_RE.search(body)
        head = found.group(0) if found else ""

    dkim = _dkim(message)
    return {
        "head": head,
        "ref": (message.get(REF_HEADER) or "").strip() or "—",
        "at": (message.get("Date") or "").strip(),
        "message_id": (message.get("Message-ID") or "").strip(),
        "from": (message.get("From") or "").strip(),
        "signature": dkim,
        "covers_head": dkim["present"] and HEAD_HEADER.lower() in dkim["headers"],
        "verified": False,          # проверка подписи здесь не производится
    }


def describe(receipt: dict[str, Any]) -> str:
    """Человеческая формулировка того, что расписка доказывает и что нет."""
    if not receipt["head"]:
        return "корень в расписке не назван: проверять нечего"

    signature = receipt["signature"]
    if not signature["present"]:
        return ("подписи нет: письмо доказывает только то, что кто-то его "
                "составил. Пересылайте карточку вложением — пересылка в теле "
                "ломает подпись")
    if not receipt["covers_head"]:
        return (f"подпись домена {signature['domain'] or '?'} есть, но заголовок "
                f"{HEAD_HEADER} в неё не входит: подписано письмо, а не корень. "
                f"Добавьте заголовок в список подписываемых на почтовом сервере")
    return (f"корень назван и входит в подпись домена {signature['domain']} "
            f"(селектор {signature['selector'] or '?'}). Саму подпись здесь не "
            f"сверяли: для этого нужен открытый ключ из DNS этого домена")


def as_sent_card(receipt: dict[str, Any]) -> dict[str, Any]:
    """Расписка в том виде, в каком её принимает verify_against_sent."""
    return {"head": receipt["head"], "at": receipt["at"],
            "ref": receipt["ref"] or receipt["message_id"]}


# --- разбор подписи ---------------------------------------------------------

def _dkim(message: Any) -> dict[str, Any]:
    raw = message.get("DKIM-Signature")
    if not raw:
        return {"present": False, "domain": "", "selector": "", "headers": [],
                "algorithm": ""}
    tags = _tags(str(raw))
    return {
        "present": True,
        "domain": tags.get("d", ""),
        "selector": tags.get("s", ""),
        "algorithm": tags.get("a", ""),
        "headers": [h.strip().lower() for h in tags.get("h", "").split(":") if h.strip()],
    }


def _tags(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.replace("\n", " ").replace("\r", " ").split(";"):
        name, _, value = part.partition("=")
        if name.strip():
            out[name.strip()] = value.strip()
    return out


def _plain_text(message: Any) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain":
                return part.get_content()
        return ""
    try:
        return message.get_content()
    except Exception:
        return ""
