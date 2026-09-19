"""将测试样板构造成 QQ Markdown 与 keyboard 原生回复。"""

from .cases import CASES, GROUPS, SPECIAL_BUTTONS


def list_cases(*, error: str = "") -> dict[str, object]:
    lines = [
        "**公式预览**",
        "> 逐项测试 QQ 客户端对 Markdown 外框、公式正文和交互的兼容性。",
        "> 发送：公式预览 编号",
    ]
    if error:
        lines.insert(1, f"> {error}")
    for group, start, end in GROUPS:
        lines.extend(("> ", f"> {group} · {start}-{end}"))
        lines.extend(
            f"> > {number}. {CASES[number - 1][0]}"
            for number in range(start, end + 1)
        )
    return _reply("\n".join(lines), current=1)


def build_preview(number: int) -> dict[str, object]:
    if number < 1 or number > len(CASES):
        return _reply(
            f"**公式预览**\n\n> 没有第 {number} 项，请输入 1-{len(CASES)}。",
            current=1,
        )
    _, content = CASES[number - 1]
    return _reply(content, current=number)


def _reply(content: str, *, current: int) -> dict[str, object]:
    return {
        "kind": "markdown",
        "content": content,
        "keyboard": _keyboard(current, len(CASES)),
    }


def _keyboard(current: int, total: int) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    special = [
        _button(f"case-{current}-{key}", label, data, behavior, style)
        for key, label, data, behavior, style in SPECIAL_BUTTONS.get(current, ())
    ]
    rows.extend(
        {"buttons": special[start : start + 3]}
        for start in range(0, len(special), 3)
    )

    navigation: list[dict[str, object]] = []
    if current > 1:
        navigation.append(
            _button("preview-prev", "上一项", f"公式预览 {current - 1}", "send", 0)
        )
    if current < total:
        navigation.append(
            _button("preview-next", "下一项", f"公式预览 {current + 1}", "send", 0)
        )
    navigation.append(_button("preview-list", "目录", "公式预览", "send", 0))
    rows.append({"buttons": navigation})
    return {"content": {"rows": rows}}


def _button(
    key: str,
    label: str,
    data: str,
    behavior: str,
    style: int,
) -> dict[str, object]:
    action_type = {"link": 0, "callback": 1, "send": 2, "fill": 2}[behavior]
    action: dict[str, object] = {
        "type": action_type,
        "data": data,
        "permission": {"type": 2},
        "unsupport_tips": "当前客户端不支持该操作.",
    }
    if action_type == 2:
        action["enter"] = behavior == "send"
        action["reply"] = behavior == "send"
    return {
        "id": f"formula-preview-{key}",
        "render_data": {"label": label, "visited_label": label, "style": style},
        "action": action,
    }
