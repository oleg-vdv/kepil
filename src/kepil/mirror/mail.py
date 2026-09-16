"""Почтовое зеркало: отправка через SMTP, перечисление через IMAP.

Разделение здесь не техническое, а смысловое. Отправка нужна тому, кто ведёт
журнал. Перечисление нужно тому, кто журнал проверяет, и именно поэтому доступ
на чтение не должен принадлежать писателю: учётные данные для отправки и для
чтения — разные, и вторые у проверяющего.

Если обе половины окажутся у одного лица, зеркало перестаёт быть зеркалом и
становится ещё одним файлом рядом с журналом.
"""

from __future__ import annotations

import email.message
import email.utils
import imaplib
import re
import smtplib
import ssl
from typing import Any, Callable

HEAD_RE = re.compile(r"sha256:[0-9a-f]{64}")
SUBJECT = "Kepil · карточка подтверждения"


class MirrorError(RuntimeError):
    """Копия не записана. Это останавливает заказ, а не пишется в лог."""


class MailMirror:
    """Отправка копии карточки. Транспорт подменяется для тестов."""

    def __init__(self, host: str, port: int, user: str, password: str,
                 sender: str, to: str,
                 transport: Callable[[email.message.EmailMessage], None] | None = None):
        self.host, self.port = host, int(port)
        self.user, self.password = user, password
        self.sender, self.to = sender or user, to
        self._transport = transport or self._smtp

    def build(self, head: str, ref: str, body: str) -> email.message.EmailMessage:
        message = email.message.EmailMessage()
        message["Subject"] = SUBJECT
        message["From"] = self.sender
        message["To"] = self.to
        message["Date"] = email.utils.formatdate(localtime=True)
        message["Message-ID"] = email.utils.make_msgid(domain="kepil.local")
        # Корень в отдельном заголовке — чтобы перечисление не зависело от того,
        # как почтовый клиент переносит строки в теле письма.
        message["X-Kepil-Head"] = head
        message["X-Kepil-Ref"] = ref or "—"
        message.set_content(f"{body}\n\nЖурнал на этот момент: {head}\n")
        return message

    def send(self, head: str, ref: str, body: str) -> dict[str, Any]:
        message = self.build(head, ref, body)
        try:
            self._transport(message)
        except MirrorError:
            raise
        except Exception as exc:
            raise MirrorError(f"копия карточки не записана: {exc}") from None
        return {"head": head, "ref": ref, "message_id": message["Message-ID"]}

    def _smtp(self, message: email.message.EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=20) as server:
            server.starttls(context=ssl.create_default_context())
            if self.user:
                server.login(self.user, self.password)
            server.send_message(message)


def enumerate_cards(host: str, user: str, password: str,
                    folder: str = "INBOX", port: int = 993,
                    opener: Callable[..., Any] | None = None) -> list[dict[str, Any]]:
    """Перечисляет карточки в почтовом ящике целиком.

    Это и есть то, чего не умеет бот: папка перечисляется вся, включая письма,
    на которые никто не отвечал. Карточка, ушедшая и оставшаяся без ответа,
    здесь остаётся — а именно её исчезновение из журнала проверка и должна
    заметить.

    Результат подаётся в `verify_against_sent`. Учётные данные для чтения
    принадлежат проверяющему: если они есть у писателя журнала, перечень
    перестаёт быть независимым.
    """
    connect = opener or (lambda: imaplib.IMAP4_SSL(host, port))
    box = connect()
    out: list[dict[str, Any]] = []
    try:
        box.login(user, password)
        box.select(folder, readonly=True)
        status, data = box.search(None, "HEADER", "X-Kepil-Head", '""')
        if status != "OK":
            status, data = box.search(None, "ALL")
        for number in (data[0].split() if data and data[0] else []):
            status, fetched = box.fetch(number, "(BODY.PEEK[HEADER])")
            if status != "OK" or not fetched:
                continue
            raw = b"".join(part[1] for part in fetched
                           if isinstance(part, tuple) and part[1])
            text = raw.decode("utf-8", "ignore")
            head = _header(text, "X-Kepil-Head") or _first_head(text)
            if not head:
                continue
            out.append({"head": head,
                        "ref": _header(text, "X-Kepil-Ref") or "почта",
                        "at": _header(text, "Date") or "",
                        "message_id": _header(text, "Message-ID") or ""})
    finally:
        try:
            box.logout()
        except Exception:
            pass
    return out


def _header(text: str, name: str) -> str:
    found = re.search(rf"^{re.escape(name)}:\s*(.+)$", text, re.M | re.I)
    return found.group(1).strip() if found else ""


def _first_head(text: str) -> str:
    found = HEAD_RE.search(text)
    return found.group(0) if found else ""
