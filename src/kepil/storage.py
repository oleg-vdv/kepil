"""Файловое хранилище состояния.

Никакой базы данных: JSON-файлы в каталоге данных. Их можно открыть, прочитать
глазами, положить в git и приложить к спору — для системы, чья ценность в
доказуемости, это важнее скорости запросов.

Каталог задаётся переменной окружения KEPIL_DATA, по умолчанию ./data.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def data_dir() -> Path:
    path = Path(os.environ.get("KEPIL_DATA", "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write(path: Path, text: str) -> None:
    """Запись через временный файл: прерванная запись не портит прежние данные."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def list_json(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    out = []
    for file in sorted(directory.glob("*.json")):
        try:
            out.append(json.loads(file.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def next_id(prefix: str, existing: list[str]) -> str:
    numbers = [int(x.rsplit("-", 1)[-1]) for x in existing
               if x.rsplit("-", 1)[-1].isdigit()]
    return f"{prefix}-{(max(numbers) + 1 if numbers else 1):04d}"
