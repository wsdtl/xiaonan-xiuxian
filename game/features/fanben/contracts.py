from __future__ import annotations

from dataclasses import dataclass


class FanbenError(ValueError):
    pass


class FanbenConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class FanbenResult:
    name: str
    race_before: str
    race_after: str
    medicine_name: str
    replayed: bool


__all__ = ["FanbenConflictError", "FanbenError", "FanbenResult"]
