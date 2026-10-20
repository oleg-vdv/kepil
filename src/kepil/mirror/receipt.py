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

Две оговорки из RFC 6376, на которых покрытие легко переоценить.
Подписывается **последний** экземпляр заголовка (5.4.2), поэтому корень
читается с конца: посредник может дописать второй `X-Kepil-Head` сверху, и
подпись сойдётся, а `message[...]` вернёт неподписанный. Чтобы дописанный
экземпляр ломал подпись, а не прятался под ней, имя должно стоять в `h=`
на раз больше, чем встречается в письме (oversigning). И тег `l=` (8.2):
он ограничивает хеш тела префиксом, всё дописанное после проходит проверку.
Непокрытый хвост считается без криптографии — его и называем.
Подписей бывает несколько: свою добавляет любой узел на пути. Расписка
опирается на подпись домена отправителя, а чужую называет чужой.
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

    # DKIM подписывает последний экземпляр (RFC 6376, 5.4.2) — его и читаем.
    instances = [str(v).strip() for v in message.get_all(HEAD_HEADER) or []]
    head = instances[-1] if instances else ""
    if not head:
        body = _plain_text(message)
        found = HEAD_RE.search(body)
        head = found.group(0) if found else ""

    sender = (message.get("From") or "").strip()
    signatures = _signatures(message)
    dkim = _choose(signatures, sender, len(instances))
    signed = dkim["headers"].count(HEAD_HEADER.lower())
    return {
        "head": head,
        "ref": (message.get(REF_HEADER) or "").strip() or "—",
        "at": (message.get("Date") or "").strip(),
        "message_id": (message.get("Message-ID") or "").strip(),
        "from": sender,
        "signature": dkim,
        "signatures": len(signatures),
        "covers_head": dkim["present"] and signed > 0,
        "head_instances": len(instances),
        # имя в h= на раз больше, чем в письме: дописанный экземпляр ломает подпись
        "oversigned": dkim["present"] and signed > len(instances),
        "uncovered_body_bytes": _uncovered_body(raw, dkim),
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
    notes = []
    if not signature["aligned"]:
        notes.append(f"домен подписи {signature['domain'] or '?'} не совпадает "
                     f"с доменом отправителя: подпись доказывает, что письмо "
                     f"прошло через этот домен, а не что карточку выдал "
                     f"отправитель")
    if receipt["signatures"] > 1:
        notes.append(f"подписей в письме: {receipt['signatures']}; взята "
                     f"подпись домена {signature['domain']}"
                     + (", домена отправителя" if signature["aligned"] else ""))
    if receipt["head_instances"] > 1:
        notes.append(f"экземпляров {HEAD_HEADER} в письме: "
                     f"{receipt['head_instances']}; подписан только "
                     f"последний, он и взят")
    if not receipt["oversigned"]:
        notes.append(f"{HEAD_HEADER} не подписан с запасом: дописанный сверху "
                     f"экземпляр подпись не сломает. Укажите имя в h= на раз "
                     f"больше, чем оно встречается")
    if receipt["uncovered_body_bytes"]:
        notes.append(f"подпись ограничена тегом l=: последние "
                     f"{receipt['uncovered_body_bytes']} байт тела ею не покрыты")
    text = (f"корень назван и входит в подпись домена {signature['domain']} "
            f"(селектор {signature['selector'] or '?'}). Саму подпись здесь не "
            f"сверяли: для этого нужен открытый ключ из DNS этого домена")
    return text + "".join(f". {n}" for n in notes)


def as_sent_card(receipt: dict[str, Any]) -> dict[str, Any]:
    """Расписка в том виде, в каком её принимает verify_against_sent."""
    return {"head": receipt["head"], "at": receipt["at"],
            "ref": receipt["ref"] or receipt["message_id"]}


# --- разбор подписи ---------------------------------------------------------

def _signatures(message: Any) -> list[dict[str, Any]]:
    return [_dkim(str(raw)) for raw in message.get_all("DKIM-Signature") or []]


def _choose(signatures: list[dict[str, Any]], sender: str,
            instances: int) -> dict[str, Any]:
    """Подпись, на которую опирается расписка, когда их несколько.

    Подпись добавить может любой узел на пути — рассылка, пересылающий
    сервер, сам посредник со своим доменом. Его подпись над дописанным
    корнем сойдётся и ничего не докажет о карточке. Поэтому сначала берутся
    подписи домена отправителя (совпадение d= с доменом From или его
    родителем, как relaxed-выравнивание в DMARC), и только среди них —
    лучшая по покрытию: корень подписан, подписан с запасом, без l=.
    """
    if not signatures:
        return {"present": False, "domain": "", "selector": "", "headers": [],
                "algorithm": "", "body_length": None,
                "canonicalization": "simple/simple", "aligned": False}
    for signature in signatures:
        signature["aligned"] = _aligned(signature["domain"], sender)
    pool = [s for s in signatures if s["aligned"]] or signatures

    def strength(signature: dict[str, Any]) -> tuple[bool, bool, bool]:
        signed = signature["headers"].count(HEAD_HEADER.lower())
        return (signed > 0, signed > instances, signature["body_length"] is None)

    return max(pool, key=strength)


def _aligned(domain: str, sender: str) -> bool:
    author = sender.rpartition("@")[2].strip(" >").lower()
    domain = domain.lower().strip(".")
    return bool(domain and author) and (author == domain
                                        or author.endswith("." + domain))


def _dkim(raw: str) -> dict[str, Any]:
    tags = _tags(raw)
    return {
        "present": True,
        "domain": tags.get("d", ""),
        "selector": tags.get("s", ""),
        "algorithm": tags.get("a", ""),
        "headers": [h.strip().lower() for h in tags.get("h", "").split(":") if h.strip()],
        "body_length": int(tags["l"]) if tags.get("l", "").isdigit() else None,
        "canonicalization": tags.get("c", "simple/simple"),
    }


def _uncovered_body(raw: bytes | str, dkim: dict[str, Any]) -> int:
    """Сколько байт канонизированного тела лежит за пределом l=.

    Ноль, если тега нет: тогда хеш покрывает тело целиком.
    """
    limit = dkim.get("body_length")
    if limit is None:
        return 0
    data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
    data = data.replace(b"\r\n", b"\n")
    body = data.split(b"\n\n", 1)[1] if b"\n\n" in data else b""
    relaxed = dkim["canonicalization"].partition("/")[2] == "relaxed"
    return max(0, len(_canonical_body(body, relaxed)) - limit)


def _canonical_body(body: bytes, relaxed: bool) -> bytes:
    """Канонизация тела по RFC 6376, 3.4.3 (simple) и 3.4.4 (relaxed)."""
    lines = body.split(b"\n")
    if relaxed:
        lines = [re.sub(rb"[ \t]+", b" ", line).rstrip(b" \t") for line in lines]
    while lines and lines[-1] == b"":
        lines.pop()
    if not lines:
        return b"" if relaxed else b"\r\n"
    return b"\r\n".join(lines) + b"\r\n"


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
