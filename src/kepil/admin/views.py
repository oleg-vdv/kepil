"""Разметка панели.

Никаких шаблонизаторов: страниц немного, а зависимость в ядре стоит дороже
удобства (см. NOTICE.md). Каждая функция возвращает готовый HTML.
"""

from __future__ import annotations

import html
from typing import Any

from ..orders.service import STATUSES
from ..professions.base import Profession
from ..professions.definition import ProfessionDefinition
from ..registry.store import STATUSES as AGENT_STATUSES
from .theme import CSS

NAV = [
    ("/", "Обзор", "overview"),
    ("/orders", "Заказы", "orders"),
    ("/professions", "Профессии", "professions"),
    ("/agents", "Агенты", "agents"),
    ("/meter", "Счётчик", "meter"),
    ("/compliance", "Комплаенс", "compliance"),
    ("/journal", "Журнал", "journal"),
    ("/settings", "Настройки", "settings"),
]

MARK = {"allow": "✓", "deny": "✕", "await_human": "?", None: "·"}
CLS = {"allow": "ok", "deny": "deny", "await_human": "wait", None: "idle"}


def e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def lines(values: list[str]) -> str:
    return e("\n".join(values))


def pairs(mapping: dict[str, Any]) -> str:
    return e("\n".join(f"{k} = {v}" for k, v in mapping.items()))


def layout(title: str, active: str, body: str, counts: dict[str, int] | None = None,
           message: tuple[str, str] | None = None) -> str:
    counts = counts or {}
    nav = []
    for href, label, key in NAV:
        count = counts.get(key)
        badge = f'<span class="count">{count}</span>' if count else ""
        on = " on" if key == active else ""
        nav.append(f'<a class="{on.strip()}" href="{href}">{label}{badge}</a>')
    banner = ""
    if message:
        kind, text = message
        banner = f'<div class="msg {e(kind)}">{e(text)}</div>'
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)} · Kepil</title><style>{CSS}</style></head><body>
<nav>
  <div class="brand"><b>Kepil</b><span>панель оператора</span></div>
  {''.join(nav)}
  <div class="foot">данные в JSON-файлах<br>журнал только дописывается</div>
</nav>
<main>{banner}{body}</main></body></html>"""


# --- обзор ------------------------------------------------------------------

def overview(orders, professions, agents, journal_state, due) -> str:
    awaiting = [o for o in orders if o.status == "awaiting"]
    ok, err = journal_state
    entries = sum(1 for _ in _iter_journal())
    attention = []
    for order in awaiting:
        attention.append(
            f'<div class="card"><h3>Ждёт подтверждения</h3>'
            f'<p>{e(order.pending["title"])} · заказ {e(order.id)} · '
            f'{e(order.client.get("name", ""))}</p>'
            f'<a href="/orders/{e(order.id)}">Открыть заказ →</a></div>')
    for passport in due:
        attention.append(
            f'<div class="card"><h3>Пересмотр рисков</h3>'
            f'<p>{e(passport["agent_id"])}: срок ежегодного пересмотра наступил '
            f'(ст. 18 п. 1 пп. 4).</p><a href="/agents">К агентам →</a></div>')
    if not ok:
        attention.append(
            f'<div class="card"><h3 style="color:var(--deny)">Журнал нарушен</h3>'
            f'<p>{e(err)}</p><a href="/journal">Проверить →</a></div>')

    rows = "".join(
        f'<tr><td class="mono"><a href="/orders/{e(o.id)}">{e(o.id)}</a></td>'
        f'<td>{e(o.client.get("name", ""))}</td>'
        f'<td>{e(professions[o.profession].name if o.profession in professions else o.profession)}</td>'
        f'<td><span class="pill {"wait" if o.status == "awaiting" else "ok" if o.status == "done" else ""}">'
        f'{e(STATUSES.get(o.status, o.status))}</span></td>'
        f'<td class="mono">{e(o.cursor)}/{e(len(professions[o.profession].steps)) if o.profession in professions else "?"}</td>'
        f'</tr>' for o in orders[:8])

    return f"""
<h1>Обзор</h1>
<p class="lede">Что сейчас в работе и что требует человека.</p>
<div class="grid g3">
  <div class="card tile"><div class="n">{len(orders)}</div><div class="l">заказов всего</div></div>
  <div class="card tile"><div class="n" style="color:var(--wait)">{len(awaiting)}</div><div class="l">ждут подтверждения</div></div>
  <div class="card tile"><div class="n">{len(professions)}</div><div class="l">профессий</div></div>
  <div class="card tile"><div class="n">{entries}</div><div class="l">записей в журнале</div></div>
</div>
{'<h2>Требует внимания</h2><div class="grid g2">' + ''.join(attention) + '</div>' if attention else ''}
<h2>Последние заказы</h2>
{'<table><tr><th>Заказ</th><th>Клиент</th><th>Профессия</th><th>Статус</th><th class="mono">Шаги</th></tr>' + rows + '</table>' if rows else '<div class="empty">Заказов пока нет. <a href="/orders">Создать первый</a></div>'}
"""


def _iter_journal():
    from ..journal import Journal
    from ..orders.service import journal_path
    return Journal(journal_path())


# --- заказы -----------------------------------------------------------------

def orders_page(orders, professions) -> str:
    options = "".join(f'<option value="{e(p.id)}">{e(p.name)}</option>'
                      for p in professions.values())
    rows = "".join(
        f'<tr><td class="mono"><a href="/orders/{e(o.id)}">{e(o.id)}</a></td>'
        f'<td>{e(o.client.get("name", ""))}<div class="mono" style="color:var(--ink-3);font-size:11.5px">'
        f'БИН {e(o.client.get("bin", "—"))}</div></td>'
        f'<td>{e(professions[o.profession].name if o.profession in professions else o.profession)}</td>'
        f'<td><span class="pill {"wait" if o.status == "awaiting" else "ok" if o.status == "done" else ""}">'
        f'{e(STATUSES.get(o.status, o.status))}</span></td>'
        f'<td class="mono">{e(o.created_at.replace("T", " "))}</td></tr>'
        for o in orders)

    return f"""
<h1>Заказы</h1>
<p class="lede">Единица работы: клиент, профессия и мандат на срок выполнения.</p>
<div class="card">
  <h3>Новый заказ</h3>
  <form method="post" action="/orders/new">
    <div class="cols">
      <div><label>Профессия</label><select name="profession">{options}</select></div>
      <div><label>Клиент</label><input type="text" name="client_name" placeholder="ТОО «Пример»" required></div>
      <div><label>БИН или ИИН</label><input type="text" name="client_bin" placeholder="123456789012" pattern="[0-9]{{12}}"></div>
      <div><label>Мандат на срок, дней</label><input type="number" name="days" value="7" min="1" max="90"></div>
    </div>
    <div class="row"><button class="primary">Создать заказ</button></div>
  </form>
</div>
<h2>Все заказы</h2>
{'<table><tr><th>Заказ</th><th>Клиент</th><th>Профессия</th><th>Статус</th><th>Создан</th></tr>' + rows + '</table>' if rows else '<div class="empty">Пока пусто.</div>'}
"""


def order_page(order, definition, journal_rows, message: str = "") -> str:
    steps = []
    for row in order.steps_view():
        step, decision = row["step"], row["decision"]
        cls = CLS.get(decision, "idle")
        why = (f'<div class="w">{e(row["reason"])}</div>'
               if decision and decision != "allow" else "")
        cost = f'{step.cost_kzt:g} ₸' if step.cost_kzt else ""
        steps.append(
            f'<div class="step {cls}"><span class="m">{MARK.get(decision, "·")}</span>'
            f'<div><div class="t">{e(step.title)}</div>'
            f'<div class="a">{e(step.action)}{" → " + e(step.system) if step.system else ""}</div>'
            f'{why}</div><span class="c">{cost}</span></div>')

    if order.pending:
        pending = f"""
        <div class="card" style="border-left:3px solid var(--wait)">
          <h3>Требуется подтверждение</h3>
          <p>{e(order.pending["title"])}</p>
          <dl class="kv">
            <dt>Действие</dt><dd class="mono">{e(order.pending["action"])}</dd>
            <dt>Получатель</dt><dd class="mono">{e(order.pending["system"] or "—")}</dd>
            <dt>Основание</dt><dd class="mono">{e(order.mandate["mandate_id"])}</dd>
            <dt>Откат</dt><dd>{e(_rollback_text(definition, order.pending["action"]))}</dd>
          </dl>
          <form method="post" action="/orders/{e(order.id)}/confirm">
            <label>Замечание (для возврата)</label>
            <input type="text" name="note" placeholder="что исправить">
            <div class="row">
              <button class="primary" name="approve" value="1">Подтвердить</button>
              <button name="approve" value="0">Вернуть</button>
            </div>
          </form>
        </div>"""
    else:
        done = order.cursor >= len(definition.steps)
        pending = (f'<div class="card"><p>'
                   f'{"Все шаги пройдены." if done else "Очередь пуста — агент работает сам."}'
                   f'</p></div>')

    if order.status == "stopped":
        stop_button = (f'<form class="inline" method="post" '
                       f'action="/orders/{e(order.id)}/resume">'
                       f'<button>Вернуть в работу</button></form>')
    else:
        stop_button = (f'<form class="inline" method="post" '
                       f'action="/orders/{e(order.id)}/stop">'
                       f'<input type="hidden" name="reason" value="остановлено оператором">'
                       f'<button class="danger">Остановить</button></form>')

    done_rows = [r for r in order.results
                 if r["decision"] == "allow" and not r.get("rolled_back")]
    if done_rows:
        options = "".join(f'<option value="{e(r["step"])}">{e(r["title"])}</option>'
                          for r in done_rows)
        rollback_block = f"""
    <h2>Откат выполненного шага</h2>
    <div class="card">
      <p>Компенсирующее действие берётся из описания профессии. Шаги, для которых
        компенсация не описана, необратимы — панель так и скажет.</p>
      <form method="post" action="/orders/{e(order.id)}/rollback">
        <div class="cols"><div><label>Шаг</label>
          <select name="step">{options}</select></div></div>
        <div class="row"><button>Откатить</button></div>
      </form>
      {f'<div class="msg ok">{e(message)}</div>' if message else ''}
    </div>

    <h2>Вернуть состояние назад</h2>
    <div class="card">
      <p>Проход идёт по действиям в обратную сторону и останавливается на первом,
        которое отменить нельзя. Что именно произойдёт — видно заранее:</p>
      <div class="msg">{_window_preview(definition, done_rows)}</div>
      <form method="post" action="/orders/{e(order.id)}/rollback-window">
        <div class="cols"><div><label>Окно</label>
          <select name="minutes">
            <option value="15">последние 15 минут</option>
            <option value="60" selected>последний час</option>
            <option value="240">последние 4 часа</option>
            <option value="1440">последние сутки</option>
          </select></div></div>
        <div class="row"><button class="danger">Откатить окно</button></div>
      </form>
    </div>"""
    else:
        rollback_block = ""

    limits = "".join(
        f'<dt>{e(key)}</dt><dd>{order.spent(key):g} из {value:g}'
        f'<div class="meter"><i style="width:{min(100, int(order.spent(key) / value * 100)) if value else 0}%"></i></div></dd>'
        for key, value in order.mandate["limits"].items())

    return f"""
<h1>Заказ {e(order.id)}</h1>
<p class="lede">{e(order.client.get("name", ""))} · {e(definition.name)} ·
  <span class="pill">{e(STATUSES.get(order.status, order.status))}</span></p>
<div class="grid g2">
  <div>
    <h2>Ход работы</h2>
    <div class="steps">{''.join(steps)}</div>
    <div class="row">
      <form class="inline" method="post" action="/orders/{e(order.id)}/step">
        <button class="primary" {"disabled" if order.pending or order.cursor >= len(definition.steps) else ""}>
          Выполнить следующий шаг</button></form>
      <form class="inline" method="post" action="/orders/{e(order.id)}/reset">
        <button>Начать заново</button></form>
      {stop_button}
    </div>
    {rollback_block}
  </div>
  <div>
    <h2>Подтверждение</h2>
    {pending}
    <h2>Мандат</h2>
    <div class="card"><dl class="kv">
      <dt>Идентификатор</dt><dd class="mono">{e(order.mandate["mandate_id"])}</dd>
      <dt>Агент</dt><dd class="mono">{e(order.agent_id)}</dd>
      <dt>Действует до</dt><dd>{e(order.mandate["valid_until"].replace("T", " ")[:16])}</dd>
      <dt>Разрешено</dt><dd class="mono" style="font-size:12px">{e(", ".join(order.mandate["allowed_actions"]))}</dd>
      <dt>Запрещено</dt><dd class="mono" style="font-size:12px">{e(", ".join(order.mandate["forbidden_actions"]))}</dd>
      <dt>Человек</dt><dd class="mono" style="font-size:12px">{e(", ".join(order.mandate["human_confirmation_required"]))}</dd>
      {limits}
    </dl></div>
  </div>
</div>
<h2>Журнал заказа</h2>
{journal_rows}
"""


def _window_preview(definition: ProfessionDefinition,
                    done_rows: list[dict[str, Any]]) -> str:
    """Что сделает откат окна — сказанное до нажатия кнопки.

    Обещание отката, которое молча не сработало, хуже отсутствия отката. Поэтому
    граница прохода называется заранее и по имени шага.

    Правило обратимости спрашивается у самой профессии, а не повторяется здесь:
    превью, разошедшееся с движком, — это то же несдержанное обещание.
    """
    profession = Profession(definition)
    undone: list[str] = []
    for row in reversed(done_rows):
        compensation = profession.rollback(row["action"])
        if not compensation:
            left = [r["title"] for r in done_rows
                    if r["title"] not in undone and r["step"] != row["step"]]
            stop = (f"Будет отменено действий: {len(undone)}. Проход остановится "
                    f"на шаге «{e(row['title'])}» — это действие необратимо")
            return stop + (f", и раньше него ничего отменено не будет: "
                           f"{e(', '.join(left))}." if left else ".")
        undone.append(row["title"])
    return f"Все выполненные действия обратимы: будет отменено {len(undone)}."


def _rollback_text(definition: ProfessionDefinition, action: str) -> str:
    if action in definition.rollback:
        return definition.rollback[action] or "откат невозможен — действие необратимо"
    return "удалить созданный черновик"


def journal_table(records: list[dict[str, Any]]) -> str:
    if not records:
        return '<div class="empty">Записей нет.</div>'
    rows = "".join(
        f'<tr><td class="mono">{e(r["seq"])}</td>'
        f'<td class="mono">{e(r["action"]["type"])}</td>'
        f'<td><span class="pill {CLS.get(r["decision"], "")}">{e(r["decision"])}</span></td>'
        f'<td class="mono">{e(r.get("step", ""))}</td>'
        f'<td class="mono">{e(r["hash"][7:19])}…</td>'
        f'<td class="mono">{e(r["prev_hash"][7:19])}…</td></tr>' for r in records)
    return ('<table><tr><th>№</th><th>Действие</th><th>Решение</th><th>Шаг</th>'
            f'<th>Хеш</th><th>Предыдущий</th></tr>{rows}</table>')


# --- профессии --------------------------------------------------------------

def professions_page(professions) -> str:
    cards = "".join(f"""
      <div class="card">
        <h3>{e(p.name)} {'<span class="pill">встроенная</span>' if p.builtin else ''}</h3>
        <p>{e(p.summary)}</p>
        <p class="mono" style="font-size:12px;color:var(--ink-3)">
          {len(p.steps)} шагов · {len(p.systems())} систем ·
          риск: {e(p.risk_class)} · автономность: средняя</p>
        <div class="row">
          <a href="/professions/{e(p.id)}"><button>Изменить</button></a>
          <form class="inline" method="post" action="/professions/{e(p.id)}/duplicate">
            <button>Копировать</button></form>
        </div>
      </div>""" for p in professions.values())

    return f"""
<h1>Профессии</h1>
<p class="lede">То, что агент умеет делать. Профессия — описание, а не код:
  её можно изменить здесь и добавить новую, не трогая ядро.</p>
<div class="grid g2">{cards}</div>
<h2>Новая профессия</h2>
<div class="card">
  <form method="post" action="/professions/new">
    <div class="cols">
      <div><label>Идентификатор<span class="hint">латиница, цифры и _</span></label>
        <input type="text" name="id" pattern="[a-z][a-z0-9_]{{1,30}}" required></div>
      <div><label>Название</label><input type="text" name="name" required></div>
    </div>
    <div class="row"><button class="primary">Создать и открыть</button></div>
  </form>
</div>
"""


def profession_form(p: ProfessionDefinition, problems: list[str] | None = None) -> str:
    issues = ("".join(f'<div class="msg err">{e(x)}</div>' for x in problems)
              if problems else "")
    risk_options = "".join(
        f'<option value="{e(r)}"{" selected" if p.risk_class == r else ""}>{e(r)}</option>'
        for r in ("минимальный", "средний", "высокий"))

    return f"""
<h1>{e(p.name)}</h1>
<p class="lede">Идентификатор <code>{e(p.id)}</code>
  {'· встроенная профессия: изменения сохранятся как ваша версия поверх неё' if p.builtin else ''}</p>
{issues}
<form method="post" action="/professions/{e(p.id)}">
  <div class="cols">
    <div><label>Название</label><input type="text" name="name" value="{e(p.name)}" required></div>
    <div><label>Степень риска<span class="hint">ст. 17 п. 1</span></label>
      <select name="risk_class">{risk_options}</select></div>
  </div>
  <label>Кратко для панели</label>
  <input type="text" name="summary" value="{e(p.summary)}">

  <label>Назначение<span class="hint">Это попадёт в паспорт агента, его видит клиент</span></label>
  <input type="text" name="purpose" value="{e(p.purpose)}" required>

  <label>Обоснование класса риска</label>
  <input type="text" name="risk_rationale" value="{e(p.risk_rationale)}">

  <label>Шаги<span class="hint">по строке на шаг: действие | заголовок | система | стоимость ₸</span></label>
  <textarea name="steps" rows="9">{e(chr(10).join(s.to_line() for s in p.steps))}</textarea>

  <div class="cols">
    <div><label>Не делает<span class="hint">границы, по строке</span></label>
      <textarea name="does_not" rows="5">{lines(p.does_not)}</textarea></div>
    <div><label>Что нужно от клиента<span class="hint">по строке</span></label>
      <textarea name="intake" rows="5">{lines(p.intake)}</textarea></div>
  </div>

  <div class="cols">
    <div><label>Требуют человека<span class="hint">шаблоны действий, по строке</span></label>
      <textarea name="irreversible" rows="4">{lines(p.irreversible)}</textarea></div>
    <div><label>Запрещено всегда<span class="hint">шаблоны действий, по строке</span></label>
      <textarea name="forbidden_actions" rows="4">{lines(p.forbidden_actions)}</textarea></div>
  </div>

  <div class="cols">
    <div><label>Лимиты<span class="hint">ключ = число, по строке</span></label>
      <textarea name="limits" rows="4">{pairs(p.limits)}</textarea></div>
    <div><label>Разрешённые системы<span class="hint">по строке; системы из шагов добавляются сами</span></label>
      <textarea name="allowed_systems" rows="4">{lines(p.allowed_systems)}</textarea></div>
  </div>

  <label>Откат<span class="hint">действие = что делаем для отмены; пустое значение означает «откат невозможен»</span></label>
  <textarea name="rollback" rows="4">{pairs(p.rollback)}</textarea>

  <div class="cols">
    <div><label>Что получает клиент</label>
      <input type="text" name="deliverable" value="{e(p.deliverable)}"></div>
    <div><label>Норматив ручной работы, минут
        <span class="hint">сколько тот же заказ занимает у человека; нужен счётчику,
        чтобы не выдумывать экономию</span></label>
      <input type="number" name="human_baseline_minutes" min="0" step="5"
             value="{p.human_baseline_minutes:g}"></div>
  </div>

  <div class="row">
    <button class="primary">Сохранить</button>
    <a href="/professions"><button type="button">Назад</button></a>
  </div>
</form>
{'' if p.builtin else f'''
<h2>Удаление</h2>
<form method="post" action="/professions/{e(p.id)}/delete"
      onsubmit="return confirm('Удалить профессию? Заказы на ней перестанут открываться.')">
  <button class="danger">Удалить профессию</button></form>'''}
"""


# --- агенты и настройки -----------------------------------------------------

def agents_page(passports) -> str:
    if not passports:
        return ('<h1>Агенты</h1><p class="lede">Паспорт выпускается автоматически '
                'при первом заказе профессии.</p><div class="empty">Пока пусто.</div>')
    def card(p: dict[str, Any]) -> str:
        next_due = (p.get("risk_review") or {}).get("next_due", "—")
        status = p.get("status", "")
        return f"""
      <div class="card">
        <h3 class="mono">{e(p["agent_id"])}</h3>
        <p>{e(p["purpose"])}</p>
        <dl class="kv">
          <dt>Статус</dt><dd><span class="pill {'ok' if status == 'active' else 'deny'}">
            {e(AGENT_STATUSES.get(status, status))}</span></dd>
          <dt>Риск / автономность</dt><dd>{e(p["risk_class"])} · {e(p["autonomy_class"])}</dd>
          <dt>Пересмотр рисков</dt><dd>{e(next_due)}</dd>
          <dt>Отпечаток</dt><dd class="mono" style="font-size:11.5px">{e(p.get("passport_hash", "")[:30])}…</dd>
        </dl>
        <div class="row">
          <form class="inline" method="post" action="/agents/{e(p["agent_id"])}/status">
            <input type="hidden" name="status" value="{'suspended' if status == 'active' else 'active'}">
            <button>{'Приостановить' if status == 'active' else 'Включить'}</button></form>
          <form class="inline" method="post" action="/agents/{e(p["agent_id"])}/reissue">
            <button>Перевыпустить</button></form>
          <form class="inline" method="post" action="/agents/{e(p["agent_id"])}/status">
            <input type="hidden" name="status" value="retired">
            <button class="danger">Вывести</button></form>
        </div>
      </div>"""

    cards = "".join(card(p) for p in passports)
    return f"""
<h1>Агенты</h1>
<p class="lede">Паспорт неизменяем: правится только статус. Приостановка
  действует немедленно — шлюз перестаёт пропускать любые действия (ст. 18 п. 2).
  «Перевыпустить» выпускает следующую версию с текущими данными организации,
  предыдущая выводится и остаётся в реестре.</p>
<div class="grid g2">{cards}</div>
"""


def journal_page(records, state, entries, anchors="") -> str:
    ok, err = state
    verdict = (f'<div class="msg ok">Целостность подтверждена. Записей: {entries}</div>'
               if ok else f'<div class="msg err">Целостность НАРУШЕНА — {e(err)}</div>')
    return f"""
<h1>Журнал</h1>
<p class="lede">Только дописывается, каждая запись связана хешем с предыдущей.
  Проверить может кто угодно: <code>npx proofbyte-agent-trace verify</code></p>
{verdict}
<div class="row" style="margin-top:0">
  <form class="inline" method="post" action="/journal/verify"><button class="primary">Проверить цепочку</button></form>
  <a href="/journal/export"><button type="button">Скачать JSONL</button></a>
</div>
<h2>Последние записи</h2>
{journal_table(records)}
<h2>Зафиксированные корни</h2>
<div class="row" style="margin-top:0">
  <form class="inline" method="post" action="/journal/anchor">
    <button>Зафиксировать корень</button></form>
</div>
{anchors}
"""


def settings_page(org, data_path) -> str:
    return f"""
<h1>Настройки</h1>
<p class="lede">Организация-оператор: она указывается в паспортах агентов как
  владелец системы и несёт ответственность по ст. 15. Уже выпущенные паспорта
  сохраняют прежние данные — после изменения перевыпустите их на странице
  «Агенты».</p>
<form method="post" action="/settings">
  <div class="cols">
    <div><label>Название</label><input type="text" name="name" value="{e(org["name"])}" required></div>
    <div><label>БИН</label><input type="text" name="bin" value="{e(org["bin"])}" pattern="[0-9]{{12}}" required></div>
    <div><label>Кто подтверждает действия</label><input type="text" name="operator" value="{e(org["operator"])}"></div>
  </div>
  <h2>Подтверждения в телефон</h2>
  <p class="lede">Пока канал не настроен, карточки ждут в панели — и ты привязан
    к компьютеру. Настроенный канал присылает действие с двумя кнопками прямо в
    Telegram: решение принимается с телефона, где бы ты ни был.</p>
  <div class="cols">
    <div><label>Токен бота
        <span class="hint">получить у @BotFather за пять минут, бесплатно</span></label>
      <input type="text" name="telegram_token" value="{e(org.get("telegram_token", ""))}"
             placeholder="1234567890:AA..."></div>
    <div><label>Твой чат
        <span class="hint">узнать у @userinfobot: он пришлёт Id</span></label>
      <input type="text" name="telegram_chat_id" value="{e(org.get("telegram_chat_id", ""))}"
             placeholder="123456789"></div>
  </div>
  <h2>Программный доступ</h2>
  <p class="lede">Нужен, чтобы Kepil спрашивали автоматизации — n8n, Make,
    собственные скрипты. Пока ключ пуст, программный интерфейс выключен целиком.</p>
  <div class="cols">
    <div><label>Ключ доступа
        <span class="hint">произвольная строка подлиннее; можно задать переменной KEPIL_API_TOKEN</span></label>
      <input type="text" name="api_token" value="{e(org.get("api_token", ""))}"
             placeholder="оставьте пустым, чтобы выключить"></div>
  </div>
  <div class="row"><button class="primary">Сохранить</button></div>
</form>
<div class="row">
  <form class="inline" method="post" action="/settings/test">
    <button>Проверить связь</button></form>
</div>
<h2>Хранение</h2>
<div class="card"><dl class="kv">
  <dt>Каталог данных</dt><dd class="mono">{e(data_path)}</dd>
  <dt>Изменить</dt><dd>переменная окружения <code>KEPIL_DATA</code></dd>
  <dt>Что внутри</dt><dd>заказы, паспорта, профессии, журнал — обычные JSON-файлы</dd>
</dl></div>
"""


# --- счётчик ----------------------------------------------------------------

def _counter_row(name: str, c) -> str:
    saved = c.saved_minutes
    saved_text = f"{saved / 60:.1f} ч" if saved is not None else "—"
    return (f'<tr><td>{e(name)}</td>'
            f'<td class="mono">{c.actions}</td>'
            f'<td class="mono">{c.denied}</td>'
            f'<td class="mono">{c.confirmations + c.returns}</td>'
            f'<td class="mono">{c.tokens or "—"}</td>'
            f'<td class="mono">{c.cost_kzt:.1f} ₸</td>'
            f'<td class="mono">{c.autonomy_share * 100:.0f} %</td>'
            f'<td class="mono">{saved_text}</td></tr>')


def meter_page(total, by_profession, by_agent, professions) -> str:
    saved = total.saved_minutes
    head = ('<tr><th>Разрез</th><th>Действий</th><th>Отказов</th><th>Решений человека</th>'
            '<th>Токенов</th><th>Стоимость</th><th>Без человека</th>'
            '<th>Замещено</th></tr>')
    prof_rows = "".join(
        _counter_row(professions[k].name if k in professions else k, v)
        for k, v in by_profession.items())
    agent_rows = "".join(_counter_row(k, v) for k, v in by_agent.items())
    return f"""
<h1>Счётчик</h1>
<p class="lede">Считается по журналу, а не по отдельной базе: цифры и
  доказательства происходят из одного источника.</p>
<div class="grid g3">
  <div class="card tile"><div class="n">{total.actions}</div><div class="l">действий всего</div></div>
  <div class="card tile"><div class="n">{total.cost_kzt:.0f} ₸</div><div class="l">на обращения к моделям</div></div>
  <div class="card tile"><div class="n">{total.autonomy_share * 100:.0f} %</div><div class="l">прошло без человека</div></div>
  <div class="card tile"><div class="n">{f"{saved / 60:.1f} ч" if saved is not None else "—"}</div>
    <div class="l">замещённого времени</div></div>
</div>
<h2>По профессиям</h2>
{f'<table>{head}{prof_rows}</table>' if prof_rows else '<div class="empty">Данных пока нет.</div>'}
<h2>По агентам</h2>
{f'<table>{head}{agent_rows}</table>' if agent_rows else '<div class="empty">Данных пока нет.</div>'}
<h2>Как читать</h2>
<div class="card">
  <p><b>Без человека</b> — доля обратимых действий, прошедших шлюз без остановки.
    Растёт по мере того, как профессия отлаживается.</p>
  <p><b>Замещено</b> — норматив ручной работы из профессии за завершённые заказы
    минус время, которое человек всё-таки потратил на подтверждения. Если норматив
    не заполнен, стоит прочерк: выдумывать экономию нельзя.</p>
  <p><b>Токенов</b> и <b>стоимость</b> — те самые величины, которые обсуждаются в
    мире как база возможного налога на ИИ. Отдельный отчёт для этого не понадобится.</p>
</div>
"""


# --- комплаенс --------------------------------------------------------------

def compliance_index(items, packs=None, selected=None) -> str:
    if not items:
        return ('<h1>Комплаенс</h1>{chooser}<p class="lede">Комплект документации '
                'собирается по выпущенному паспорту агента.</p>'
                '<div class="empty">Сначала создайте заказ — паспорт выпустится сам.</div>')
    cards = "".join(f"""
      <div class="card">
        <h3 class="mono">{e(item["agent_id"])}</h3>
        <p>{e(item["profession_name"])} · риск: {e(item["risk_class"])}</p>
        <dl class="kv">
          <dt>Обязательных документов</dt><dd>{item["required"]}</dd>
          <dt>Всего в комплекте</dt><dd>{item["total"]}</dd>
          <dt>Мест для человека</dt><dd>{item["todo"]}</dd>
        </dl>
        <div class="row">
          <a href="/compliance/{e(item["agent_id"])}"><button>Открыть комплект</button></a>
        </div>
      </div>""" for item in items)
    chooser = ""
    if packs:
        current = selected if selected in packs else "generic"
        chips = []
        for pack_id, pack in packs.items():
            mark = "on" if pack_id == current else ""
            chips.append(f'<a class="pill {mark}" href="/compliance?pack={e(pack_id)}">'
                         f'{e(pack.name)}</a>')
        missing = "" if len(packs) > 1 else (
            '<div class="subtle">Пакет под законодательство Казахстана '
            '(Закон № 230-VIII, приказ № 95/НҚ) не установлен. '
            'Положите файл пакета в каталог данных, подкаталог <code>packs</code>.</div>')
        chooser = (f'<h2>Пакет документации</h2><div class="row" style="margin-top:0">'
                   f'{"".join(chips)}</div>{missing}')
    return f"""
<h1>Комплаенс</h1>
<p class="lede">Приказ № 95/НҚ от 25.02.2026: состав документации зависит от
  степени риска. Документы собираются из паспорта, описания профессии и журнала.</p>
<div class="grid g2">{cards}</div>
"""


def compliance_set(agent_id: str, documents, selected, body: str) -> str:
    tabs = "".join(
        f'<a href="/compliance/{e(agent_id)}?doc={e(d.key)}">'
        f'<button {"class=primary" if d.key == selected else ""}>{e(d.title)}'
        f'{" ·" if d.required else ""}</button></a> ' for d in documents)
    return f"""
<h1 class="mono">{e(agent_id)}</h1>
<p class="lede">Точка после названия означает, что документ обязателен для этой
  степени риска. Остальные не требуются приказом, но нужны при аудите и в споре.</p>
<div class="row" style="margin-top:0">{tabs}</div>
<div class="row">
  <a href="/compliance/{e(agent_id)}/download"><button class="primary">Скачать комплект</button></a>
  <a href="/compliance"><button>Ко всем агентам</button></a>
</div>
<h2>{e(next((d.title for d in documents if d.key == selected), ""))}</h2>
<div class="card"><pre class="mono" style="white-space:pre-wrap;margin:0;font-size:12.5px">{e(body)}</pre></div>
"""


# --- журнал: якоря ----------------------------------------------------------

def anchors_block(items) -> str:
    if not items:
        return ('<div class="empty">Корень ещё не фиксировался. Фиксация нужна '
                'затем, что цепочку хешей можно пересчитать целиком — а '
                'зафиксированный ранее корень в переписанном журнале не найдётся.</div>')
    rows = "".join(
        f'<tr><td class="mono">{e(a["ts"].replace("T", " "))}</td>'
        f'<td class="mono">{a["seq"]}</td><td class="mono">{a["entries"]}</td>'
        f'<td class="mono">{e(a["head"][7:27])}…</td>'
        f'<td>{"подписан" if a.get("signature") else "без подписи ЭЦП"}</td></tr>'
        for a in reversed(items))
    return ('<table><tr><th>Когда</th><th>Запись</th><th>Всего</th>'
            f'<th>Корень</th><th>Подпись</th></tr>{rows}</table>')
