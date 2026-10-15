"""生育命令的输入。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BirthCommand:
    """生育命令没有参数（对象就是当前同行道侣）。"""

    query: str = ""


def parse(message: str) -> BirthCommand:
    return BirthCommand(query=str(message or "").strip())
