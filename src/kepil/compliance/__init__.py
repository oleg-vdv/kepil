"""Комплект документации на систему ИИ: движок отдельно, тексты отдельно.

Документы собираются из паспорта агента, описания профессии и журнала действий:
комплаенс, набранный руками, расходится с реальностью на второй неделе, а
собранный из журнала — не может.

Открытая часть содержит универсальный пакет по международной практике. Пакеты
под конкретное законодательство кладутся в каталог данных (см. packs.py).
"""

from .checklist import Act, Check, Checklist, Stage, checklists_dir
from .checklist import get as get_checklist
from .checklist import load_all as load_checklists
from .generator import Document, available_packs, build, missing_marks
from .packs import Pack, installed_dir
from .survey import Answer, Report, Row, run as run_survey

__all__ = ["Document", "Pack", "build", "missing_marks", "available_packs",
           "installed_dir", "Checklist", "Stage", "Check", "Act",
           "load_checklists", "get_checklist", "checklists_dir",
           "run_survey", "Report", "Row", "Answer"]
