"""HTTP-панель оператора.

Стандартная библиотека, серверный рендеринг, обычные формы. Ни одного внешнего
пакета: ядро должно ставиться в закрытом контуре и проходить требование о доле
локализации (см. NOTICE.md).

Запуск:
    python -m kepil.admin            # http://localhost:7317
    python -m kepil.admin 8080
"""

from __future__ import annotations

import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from ..journal import Journal
from ..orders import service as orders
from ..professions import definition as professions
from ..registry import store as agents
from ..storage import data_dir
from . import views

Params = dict[str, str]
Handler = Callable[["Request"], "Response"]


class Response:
    def __init__(self, body: str = "", status: int = 200, redirect: str | None = None,
                 content_type: str = "text/html; charset=utf-8",
                 raw: bytes | None = None, filename: str | None = None) -> None:
        self.body, self.status, self.redirect = body, status, redirect
        self.content_type, self.raw, self.filename = content_type, raw, filename


class Request:
    def __init__(self, path: str, params: Params, query: Params) -> None:
        self.path, self.params, self.query = path, params, query

    def form(self, name: str, default: str = "") -> str:
        return self.params.get(name, default).strip()

    def lines(self, name: str) -> list[str]:
        return [x.strip() for x in self.params.get(name, "").splitlines() if x.strip()]

    def pairs(self, name: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in self.lines(name):
            key, _, value = line.partition("=")
            if key.strip():
                out[key.strip()] = value.strip()
        return out


# --- страницы ---------------------------------------------------------------

def _counts() -> dict[str, int]:
    awaiting = sum(1 for o in orders.list_orders() if o.status == "awaiting")
    return {"orders": awaiting} if awaiting else {}


def page(title: str, active: str, body: str, message=None) -> Response:
    return Response(views.layout(title, active, body, _counts(), message))


def overview(_: Request) -> Response:
    return page("Обзор", "overview", views.overview(
        orders.list_orders(), professions.load_all(), agents.all_passports(),
        orders.verify_journal(), agents.review_due()))


def orders_list(_: Request) -> Response:
    return page("Заказы", "orders",
                views.orders_page(orders.list_orders(), professions.load_all()))


def order_create(request: Request) -> Response:
    client = {"name": request.form("client_name"),
              "bin": request.form("client_bin") or "000000000000"}
    days = int(request.form("days") or 7)
    order = orders.create(request.form("profession"), client, days=days)
    return Response(redirect=f"/orders/{order.id}")


def order_view(request: Request) -> Response:
    order = orders.get(request.query["id"])
    records = [r for r in Journal(orders.journal_path()) if r.get("order_id") == order.id]
    return page(f"Заказ {order.id}", "orders",
                views.order_page(order, order.definition(),
                                 views.journal_table(records)))


def order_step(request: Request) -> Response:
    orders.run_next(orders.get(request.query["id"]))
    return Response(redirect=f"/orders/{request.query['id']}")


def order_confirm(request: Request) -> Response:
    order = orders.get(request.query["id"])
    orders.confirm(order, request.form("approve") == "1", request.form("note"))
    return Response(redirect=f"/orders/{order.id}")


def order_reset(request: Request) -> Response:
    order = orders.get(request.query["id"])
    order.cursor, order.results, order.pending, order.status = 0, [], None, "new"
    order.mandate["spent"] = {}
    order.save()
    return Response(redirect=f"/orders/{order.id}")


def professions_list(_: Request) -> Response:
    return page("Профессии", "professions",
                views.professions_page(professions.load_all()))


def profession_view(request: Request) -> Response:
    definition = professions.get(request.query["id"])
    return page(definition.name, "professions", views.profession_form(definition))


def profession_save(request: Request) -> Response:
    current = professions.get(request.query["id"])
    try:
        steps = [professions.Step.parse(line, i)
                 for i, line in enumerate(request.lines("steps"))]
    except ValueError as exc:
        return page(current.name, "professions",
                    views.profession_form(current), ("err", str(exc)))

    limits: dict[str, float] = {}
    for key, value in request.pairs("limits").items():
        try:
            limits[key] = float(value.replace(",", "."))
        except ValueError:
            return page(current.name, "professions", views.profession_form(current),
                        ("err", f"лимит «{key}»: нужно число"))

    updated = professions.ProfessionDefinition(
        id=current.id,
        name=request.form("name") or current.name,
        summary=request.form("summary"),
        purpose=request.form("purpose"),
        does_not=request.lines("does_not"),
        intake=request.lines("intake"),
        steps=steps,
        irreversible=request.lines("irreversible"),
        rollback=request.pairs("rollback"),
        limits=limits,
        allowed_systems=request.lines("allowed_systems"),
        forbidden_actions=request.lines("forbidden_actions"),
        risk_class=request.form("risk_class") or current.risk_class,
        risk_rationale=request.form("risk_rationale"),
        deliverable=request.form("deliverable"),
    )
    problems = updated.validate()
    if problems:
        return page(updated.name, "professions",
                    views.profession_form(updated, problems))
    professions.save(updated)
    return Response(redirect="/professions")


def profession_new(request: Request) -> Response:
    new_id, name = request.form("id"), request.form("name")
    blank = professions.ProfessionDefinition(
        id=new_id, name=name or new_id, summary="",
        purpose="Опишите, что делает агент этой профессии",
        does_not=["опишите границы: чего агент не делает никогда"],
        intake=["что нужно получить от клиента до старта"],
        steps=[professions.Step.parse("read:source | Первый шаг", 0)],
    )
    problems = blank.validate()
    if problems:
        return page("Профессии", "professions",
                    views.professions_page(professions.load_all()),
                    ("err", "; ".join(problems)))
    professions.save(blank)
    return Response(redirect=f"/professions/{new_id}")


def profession_duplicate(request: Request) -> Response:
    source = request.query["id"]
    existing = professions.load_all()
    new_id = f"{source}_copy"
    index = 2
    while new_id in existing:
        new_id, index = f"{source}_copy{index}", index + 1
    professions.duplicate(source, new_id, f"{existing[source].name} (копия)")
    return Response(redirect=f"/professions/{new_id}")


def profession_delete(request: Request) -> Response:
    try:
        professions.delete(request.query["id"])
    except KeyError as exc:
        return page("Профессии", "professions",
                    views.professions_page(professions.load_all()), ("err", str(exc)))
    return Response(redirect="/professions")


def agents_list(_: Request) -> Response:
    return page("Агенты", "agents", views.agents_page(agents.all_passports()))


def agent_status(request: Request) -> Response:
    agents.set_status(request.query["id"], request.form("status"))
    return Response(redirect="/agents")


def journal_view(request: Request) -> Response:
    records = list(Journal(orders.journal_path()))
    return page("Журнал", "journal",
                views.journal_page(records[-40:], orders.verify_journal(), len(records)))


def journal_export(_: Request) -> Response:
    path = orders.journal_path()
    body = path.read_bytes() if path.exists() else b""
    return Response(raw=body, content_type="application/x-ndjson",
                    filename="journal.jsonl")


def settings_view(_: Request) -> Response:
    return page("Настройки", "settings",
                views.settings_page(agents.settings(), data_dir().resolve()))


def settings_save(request: Request) -> Response:
    agents.save_settings({"name": request.form("name"), "bin": request.form("bin"),
                          "operator": request.form("operator")})
    return Response(redirect="/settings")


ROUTES: list[tuple[str, str, Handler]] = [
    ("GET", "/", overview),
    ("GET", "/orders", orders_list),
    ("POST", "/orders/new", order_create),
    ("GET", "/orders/<id>", order_view),
    ("POST", "/orders/<id>/step", order_step),
    ("POST", "/orders/<id>/confirm", order_confirm),
    ("POST", "/orders/<id>/reset", order_reset),
    ("GET", "/professions", professions_list),
    ("POST", "/professions/new", profession_new),
    ("GET", "/professions/<id>", profession_view),
    ("POST", "/professions/<id>", profession_save),
    ("POST", "/professions/<id>/duplicate", profession_duplicate),
    ("POST", "/professions/<id>/delete", profession_delete),
    ("GET", "/agents", agents_list),
    ("POST", "/agents/<id>/status", agent_status),
    ("GET", "/journal", journal_view),
    ("POST", "/journal/verify", journal_view),
    ("GET", "/journal/export", journal_export),
    ("GET", "/settings", settings_view),
    ("POST", "/settings", settings_save),
]


def resolve(method: str, path: str) -> tuple[Handler, Params] | None:
    """Сопоставляет путь с маршрутом; <id> — единственный вид параметра."""
    parts = [p for p in path.strip("/").split("/") if p]
    for route_method, pattern, handler in ROUTES:
        if route_method != method:
            continue
        expected = [p for p in pattern.strip("/").split("/") if p]
        if len(expected) != len(parts):
            continue
        query: Params = {}
        for want, got in zip(expected, parts):
            if want == "<id>":
                query["id"] = urllib.parse.unquote(got)
            elif want != got:
                break
        else:
            return handler, query
    return None


class _Handler(BaseHTTPRequestHandler):
    server_version = "Kepil"

    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        path = urllib.parse.urlparse(self.path).path
        found = resolve(method, path)
        if not found:
            self._send(Response("<h1>404</h1><p>Страница не найдена. "
                                "<a href=\"/\">На главную</a></p>", status=404))
            return
        handler, query = found
        params: Params = {}
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            params = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
        try:
            response = handler(Request(path, params, query))
        except KeyError as exc:
            response = Response(f"<h1>Не найдено</h1><p>{exc}</p>", status=404)
        except Exception as exc:  # ошибка панели не должна ронять сервер
            response = Response(f"<h1>Ошибка</h1><pre>{exc!r}</pre>", status=500)
        self._send(response)

    def _send(self, response: Response) -> None:
        if response.redirect:
            self.send_response(303)
            self.send_header("Location", response.redirect)
            self.end_headers()
            return
        body = response.raw if response.raw is not None else response.body.encode("utf-8")
        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(len(body)))
        if response.filename:
            self.send_header("Content-Disposition",
                             f'attachment; filename="{response.filename}"')
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = 7317, host: str = "127.0.0.1") -> None:
    print(f"Kepil · панель оператора: http://localhost:{port}")
    print(f"данные: {data_dir().resolve()}")
    ThreadingHTTPServer((host, port), _Handler).serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 7317)
