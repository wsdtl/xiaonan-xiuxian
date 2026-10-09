from __future__ import annotations

from dataclasses import dataclass


class XigenError(ValueError):
    pass


class XigenConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class XigenResult:
    name: str
    before: str
    after: str
    medicine_name: str
    repeated: int
    replayed: bool


__all__ = ['XigenConflictError', 'XigenError', 'XigenResult']
