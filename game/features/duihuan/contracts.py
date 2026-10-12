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




@dataclass(frozen=True)
class DuihuanAction:
    """兑换码回执上的动作，字段名与 CommandAction 契约一致。"""

    action_id: str
    label: str
    command: str
    behavior: str
    style: str


__all__ = ['DuihuanConflictError', 'DuihuanError', 'DuihuanResult']
