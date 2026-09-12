"""Kepil — слой подотчётности для ИИ-агентов."""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("kepil")
except PackageNotFoundError:          # запуск из исходников без установки
    __version__ = "0.2.1"
