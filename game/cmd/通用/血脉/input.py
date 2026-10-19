"""血脉命令的输入解析。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class XuemaiCommand:
    """血脉命令的参数。"""

    subcommand: str = ""
    """子命令（第一版只有「族谱」）。"""

    query: str = ""
    """可选的筛选词（名字或编号）。"""


def parse(message: str) -> XuemaiCommand:
    """把命令后面的文字解析成「子命令 + 筛选词」。"""

    parts = str(message or "").strip().split()
    if not parts:
        return XuemaiCommand()
    if parts[0] in ("族谱", "族谱血", "家谱"):
        return XuemaiCommand(subcommand="族谱", query=" ".join(parts[1:]).strip())
    return XuemaiCommand(subcommand=parts[0], query=" ".join(parts[1:]).strip())
