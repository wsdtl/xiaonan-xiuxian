"""可点命令判据：正文里的无边框按钮必须真的能点。

两组检查：

1. **静态**：M.command(...) 的标签不许带 tone。标签一旦带 tone，markdown 会把它
   渲染成公式（dollar 包起来的那一层）再包进 Markdown 链接，而 QQ 不解析公式内的链接
   ——按钮就废了（见 launch/adapter/qq_protocol/render.py 的 force_formula）。
2. **运行期**：按三种危险写法各渲染一次，断言链接文本里没有公式标记。构造层虽然
   会把标签规范化成纯文本，这里仍然实测一遍，防的是规范化被绕过或渲染器改回去。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查可点命令.py

**退出码：0 = 干净，1 = 有不可点的按钮。**
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GAME = ROOT / "game"
COMMAND_CALL = re.compile(r"M\.command\(")
TONE_IN_LABEL = re.compile(r'tone\s*=\s*"[a-z]+"')
FORMULA_MARK = "$"


def _first_argument(text: str, open_paren: int) -> str:
    """取 M.command( 的第一个实参（深度与字符串都算准，跨行也行）。"""

    i, depth, in_str, quote = open_paren, 1, False, ""
    while i < len(text) and depth:
        ch = text[i]
        if in_str:
            if ch == quote:
                in_str = False
        else:
            if ch in (chr(34) + chr(39)):
                in_str, quote = True, ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 1:
                break
        i += 1
    return text[open_paren:i]


def check_labels_have_no_tone() -> list[str]:
    """标签带 tone 就是公式标签，QQ 上点不动。"""

    problems: list[str] = []
    for path in sorted(GAME.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in COMMAND_CALL.finditer(text):
            label = _first_argument(text, match.end())
            if TONE_IN_LABEL.search(label):
                line = text[: match.start()].count("\n") + 1
                problems.append(
                    path.relative_to(ROOT).as_posix()
                    + ":" + str(line)
                    + " M.command 的标签带了 tone（公式标签在 QQ 上点不动）"
                )
    return problems


def _argument(text: str, open_paren: int, index: int) -> str:
    """取 M.command( 的第 index 个实参（从 0 数，深度与字符串都算准）。"""

    i, depth, in_str, quote, seen = open_paren, 1, False, "", 0
    start = open_paren
    while i < len(text) and depth:
        ch = text[i]
        if in_str:
            if ch == quote:
                in_str = False
        else:
            if ch in (chr(34) + chr(39)):
                in_str, quote = True, ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "," and depth == 1:
                seen += 1
                start = i + 1
                if seen > index:
                    return text[start:i].strip()
        i += 1
    return text[start:i].strip()


def check_commands_are_registered() -> list[str]:
    """正文内联按钮指向的命令必须真的存在，否则玩家点了没反应。"""

    from game.cmd.command import registered_command_routes

    heads = set()
    for route in registered_command_routes():
        head = str(route[0] if isinstance(route, tuple) else route).strip()
        if head:
            heads.add(head)
    problems: list[str] = []
    for path in sorted(GAME.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in COMMAND_CALL.finditer(text):
            target = _argument(text, match.end(), 1)
            quote = chr(34) if chr(34) in target else chr(39)
            if quote not in target:
                continue
            body = target.split(chr(123))[0].strip()
            if body[:1] == chr(102):
                body = body[1:]
            body = body.strip().strip(chr(34)).strip(chr(39))
            for part in body.split(chr(124)):
                word = part.strip().split()[0] if part.strip() else chr(0)
                if word and word != chr(0) and word not in heads:
                    line = text[: match.start()].count(chr(10)) + 1
                    problems.append(
                        path.relative_to(ROOT).as_posix()
                        + chr(58) + str(line)
                        + chr(32) + word
                    )
    return problems


def check_location_panel_callers() -> list[str]:
    """「当前地点完整面板」只许 `位置` 与 `行路` 的组件去取。

    依据 game/cmd/说明.md 的按钮归属一节：玩家回复只允许三类按钮，头两类都与
    「当前地点完整操作面板」有关——位置/去 成功抵达时展示它，地点专属业务结束时
    复现它。三类之外不得附加按钮，所以构造这个面板的函数只能在上述组件里被调用。
    """

    panel_functions = ("position_actions", "current_location_actions", "gate_actions")
    allowed = ("通用/位置", "通用/行路")
    problems: list[str] = []
    for path in sorted((ROOT / "game" / "cmd").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if any(part in relative for part in allowed):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "def " in line:
                continue
            for name in panel_functions:
                if name + "(" in line and "features." in line:
                    problems.append(
                        relative + ":" + str(number)
                        + " 三类之外的组件取了当前地点面板：" + name
                    )
    return problems


def check_paged_pages_have_way_back() -> list[str]:
    """带翻页的页面必须有一个「返回」类按钮，否则玩家点进去出不来。

    依据委托方原话「无边框按钮 遇到多种情况下放返回」：一页里摆着上一页/下一页，
    却没有回到本业务首页或地点面板的动作，玩家就只能靠手打命令。
    """

    import json

    problems: list[str] = []
    root = pathlib.Path(__file__).resolve().parents[2]
    for path in sorted((root / "data").rglob("按钮.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 不是 JSON 就跳过
            continue
        if not isinstance(body, list):
            continue
        pages: dict[str, list[str]] = {}
        for item in body:
            if not isinstance(item, dict):
                continue
            page = str(item.get("页面") or "(未分组)")
            pages.setdefault(page, []).append(str(item.get("名称") or ""))
        for page, names in pages.items():
            if not any("上一页" in n or "下一页" in n for n in names):
                continue
            if not any("返回" in n or n.endswith("回") for n in names):
                problems.append(
                    path.relative_to(root).as_posix() + " 页面「" + page
                    + "」有翻页却没有返回：" + " / ".join(names)
                )
    return problems


def check_button_data_commands_are_registered() -> list[str]:
    """展示数据集里的按钮（data/**/按钮.json）命令必须已注册。

    正文内联按钮与键盘按钮的目标，静态判据能守一半；按钮数据是纯 JSON，
    打错一个字就是点了没反应的死按钮，这里逐个核一遍。
    """

    import json

    from game.cmd.command import registered_command_routes

    heads = set()
    for route in registered_command_routes():
        head = str(route[0] if isinstance(route, tuple) else route).strip()
        if head:
            heads.add(head)
    problems: list[str] = []
    root = pathlib.Path(__file__).resolve().parents[2]
    for path in sorted((root / "data").rglob("按钮.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 不是 JSON 就跳过
            continue
        if not isinstance(body, list):
            continue
        for item in body:
            if not isinstance(item, dict):
                continue
            command = str(item.get("命令") or "").strip()
            if not command:
                continue
            word = command.split()[0]
            if word not in heads:
                problems.append(
                    path.relative_to(root).as_posix()
                    + " " + str(item.get("名称")) + " " + word
                )
    return problems


def _render(message: object) -> str:
    from launch.adapter.qq_protocol.render import render_qq_message

    payload = render_qq_message(message)
    return payload["content"] if isinstance(payload, dict) else str(payload)


def check_rendered_links_are_plain() -> list[str]:
    """三种危险写法渲染出来，链接文本里都不许出现公式标记。"""

    from message import M

    hazard = M.command(M.text("透甲", tone="mystic"), "查看 400001")
    samples = {
        "带 tone 的标签": M.document().header("判据").section("栏").line(hazard).build(),
        "纯文本标签": (
            M.document().header("判据").section("栏")
            .line(M.command("透甲", "查看 400001")).build()
        ),
        "caption 行里的命令": (
            M.document().header("判据").section("栏")
            .small(M.command(M.text("透甲", tone="mystic"), "查看 400001")).build()
        ),
    }
    problems: list[str] = []
    for label, message in samples.items():
        for target in re.findall(r"\[([^\]]*)\]\(mqqapi://", _render(message)):
            if FORMULA_MARK in target:
                problems.append(label + "：链接文本里出现了公式 " + target[:48])
    return problems


def check_branches_resolve() -> list[str]:
    """A|B <参数> 只认已注册的分支；够参数的直接发，还差参数的只填入。"""

    from game.cmd.通用.帮助.branches import branches_of, is_complete

    problems: list[str] = []
    cases = {
        "查看|借阅功法 400001": 2,
        "查看 400001 | 人物装配 功法 400001 03": 2,
        "查看|装配 400001": 1,
        "查看 400001": 0,
    }
    for text, expected in cases.items():
        found = branches_of(text)
        if len(found) != expected:
            problems.append(text + " 解析出 " + str(len(found)) + " 个分支，期望 " + str(expected))
    known = dict(branches_of("查看|借阅功法 400001"))
    if known.get("查看") and not is_complete(known["查看"]):
        problems.append("完整命令「查看 400001」被当成不完整")
    if known.get("借阅功法") and is_complete(known["借阅功法"]):
        problems.append("还差槽位的「借阅功法 400001」被当成完整")
    return problems

USAGE_BLOCK = re.compile(r'"usage"\s*:\s*\(([^)]*)\)', re.S)
USAGE_MACHINE_WORDS = ("状态键", "实例键", "条目键", "条目", "机器键", "无灵宝")
USAGE_MACHINE_KEY = re.compile(r"\d{6}:\d{2}")


def check_usages_have_no_machine_words() -> list[str]:
    """命令的 `usage` 是给玩家看的用法，不许出现机器词与机器键形态。

    真出过事：`锁阵 万珍殿阵法条目`、`发放万珍殿 … 条目编号`——玩家被要求敲内部键，
    而真正受理的是「阵法名[灵宝名]」。委托方 2026-10 的口径：中文有中文的显示与输入定义，
    id 化只**默默受理**、不必对外宣传。
    """

    problems: list[str] = []
    for path in sorted(GAME.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in USAGE_BLOCK.finditer(text):
            block = match.group(1)
            line = text[: match.start()].count("\n") + 1
            where = path.relative_to(ROOT).as_posix() + ":" + str(line)
            for word in USAGE_MACHINE_WORDS:
                if word in block:
                    problems.append(
                        where + " usage 里出现机器词「" + word + "」：" + block.strip()[:60]
                    )
            hit = USAGE_MACHINE_KEY.search(block)
            if hit:
                problems.append(
                    where + " usage 里出现机器键形态「" + hit.group(0) + "」：" + block.strip()[:60]
                )
    return problems


CHECKS = (
    ("标签不带 tone", check_labels_have_no_tone),
    ("链接文本无公式", check_rendered_links_are_plain),
    ("多分支解析", check_branches_resolve),
    ("按钮目标已注册", check_commands_are_registered),
    ("按钮数据命令已注册", check_button_data_commands_are_registered),
    ("地点面板只许位置/行路取", check_location_panel_callers),
    ("翻页页必须有返回", check_paged_pages_have_way_back),
    ("用法不露机器词", check_usages_have_no_machine_words),
)


def main() -> int:
    problems: list[str] = []
    for name, check in CHECKS:
        found = check()
        print("  [" + name + "] " + ("干净" if not found else str(len(found)) + " 处"))
        for item in found[:20]:
            print("    " + item)
        problems.extend(found)
    if problems:
        print("可点命令 " + str(len(problems)) + " 处有问题")
        return 1
    print("可点命令判据通过：" + str(len(CHECKS)) + " 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
