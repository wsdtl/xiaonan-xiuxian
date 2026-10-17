"""生育与求子的命令输入。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BirthCommand:
    """生育命令没有参数（对象就是当前同行道侣）。"""

    query: str = ""


@dataclass(frozen=True)
class AskCommand:
    """求子命令：先看第一个词是动作，其余是对象。"""

    action: str
    argument: str


def parse(message: str) -> BirthCommand:
    return BirthCommand(query=str(message or "").strip())


def parse_request(message: str) -> AskCommand:
    text = " ".join(str(message or "").split())
    if not text:
        return AskCommand("pending", "")
    head, _, rest = text.partition(" ")
    head = head.strip()
    rest = rest.strip()
    if head in ("同意", "答应"):
        return AskCommand("agree", rest)
    if head in ("拒绝", "回绝"):
        return AskCommand("refuse", rest)
    if head in ("待办", "请求", "看"):
        return AskCommand("pending", "")
    return AskCommand("ask", text)
