"""命令主标题判据：一层主标题必须是触发命令原文的无边框按钮，且带已登记的图标。

主标题由统一回复层按触发命令注入（见 tools/基准/说明.md 的施工单）。这里正面断言它
存在且形态正确——检查消息零信息 那边把"正文第一个一层行"当主标题跳过，靠的就是本判据兜底。

退出码 0 表示干净，1 表示有问题。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launch.adapter.qq_protocol.payload import payload_text  # noqa: E402
from launch.adapter.qq_protocol.render import render_qq_message  # noqa: E402
from message import M, reset_command_title, set_command_title  # noqa: E402
from message.icons import icon_for  # noqa: E402

#: 触发命令原文 → 该命令的帮助分类图标（与 game/cmd/help_icons.py 的表一致）。
CASES = (
    ("帮助", "system"),
    ("人物", "player"),
    ("纳戒", "world"),
    ("地图", "map"),
)

BUTTON_MARK = "mqqapi://aio/inlinecmd"


def _card():
    """造一张普通卡：主标题由 set_command_title 注入，与真实回复同一条路。"""

    return M.document().section("说明", icon="inventory").line("示例正文").build()


def audit() -> list[str]:
    """返回全部问题描述；空列表表示干净。"""

    problems: list[str] = []
    for 原文, 图标 in CASES:
        token = set_command_title(原文, icon=图标)
        try:
            载荷 = render_qq_message(_card())
            正文 = payload_text(载荷)
        finally:
            reset_command_title(token)
        行 = [x for x in 正文.split("\n") if x.strip()]
        首 = 行[0] if 行 else ""
        if not 首.startswith("> "):
            problems.append(f"{原文}：渲染后第一行不是一层主标题：{首!r}")
            continue
        期望图标 = icon_for(图标)
        if 期望图标 not in 首:
            problems.append(f"{原文}：主标题少了图标 {期望图标!r}：{首!r}")
        if 原文 not in 首:
            problems.append(f"{原文}：主标题里没有命令原文：{首!r}")
        整个 = str(载荷)
        if BUTTON_MARK not in 整个:
            problems.append(f"{原文}：主标题没有做成无边框按钮")
        elif "enter=false" not in 整个:
            problems.append(f"{原文}：行内按钮应当只填入（enter=false）")
    if not problems:
        print(f"命令标题判据通过：{len(CASES)} 条命令的主标题都带图标且是只填入按钮")
    return problems


def main() -> int:
    problems = audit()
    if problems:
        print(f"命令标题问题 {len(problems)} 处：")
        for problem in problems:
            print(f"  {problem}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())