from __future__ import annotations

from dataclasses import dataclass


class WangyeError(ValueError):
    pass


class WangyeConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class WangyeScope:
    user_id: str
    name: str


__all__ = ['WangyeConflictError', 'WangyeError', 'WangyeScope']
