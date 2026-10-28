"""展示层源头约束：标题不接编号，实体名接命令。"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from message import CommandLink

from game.cmd.presentation import linked_name_line


def test_linked_name_line_turns_name_into_command() -> None:
    parts = linked_name_line("赠予 \u0000 一株", "云参")
    links = [part for part in parts if isinstance(part, CommandLink)]
    assert [link.command for link in links] == ["查看 云参"]
    rendered = "".join(
        "".join(span.value for span in part.label)
        if isinstance(part, CommandLink)
        else part.value
        for part in parts
    )
    assert rendered == "赠予 云参 一株"


def test_no_literal_six_digit_title_in_command_layer() -> None:
    offenders: list[str] = []
    for path in Path("game/cmd").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "send_game_reply":
                continue
            for keyword in node.keywords:
                if keyword.arg != "title" or not isinstance(keyword.value, ast.Constant):
                    continue
                if re.search(r"(?<!\d)\d{6}(?!\d)", str(keyword.value.value)):
                    offenders.append(f"{path}:{node.lineno}")
    assert not offenders, offenders
