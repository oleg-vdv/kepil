"""Реестр агентов: паспорта версий и их состояние."""

from . import store
from .passport import AgentPassport

__all__ = ["AgentPassport", "store"]
