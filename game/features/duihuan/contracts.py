from __future__ import annotations

from dataclasses import dataclass


class DuihuanError(ValueError):
    pass


class DuihuanConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class DuihuanResult:
    code: str
    code_id: str
    name: str
    granted: str
    replayed: bool


__all__ = ['DuihuanConflictError', 'DuihuanError', 'DuihuanResult']
