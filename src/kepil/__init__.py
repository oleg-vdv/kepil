"""Kepil — слой подотчётности для ИИ-агентов."""

from importlib.metadata import PackageNotFoundError, version as _version
from pathlib import Path


def _from_pyproject() -> str:
    """Версия из pyproject при запуске из исходников без установки.

    Дублировать номер версии в коде нельзя: копия расходится с pyproject молча,
    и наружу — в рукопожатие MCP, в отчёты — уезжает неправда.
    """
    path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("version"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "0+unknown"


try:
    __version__ = _version("kepil")
except PackageNotFoundError:
    __version__ = _from_pyproject()
