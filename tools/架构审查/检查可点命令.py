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
            if ch in "\"'":
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
    cases = {"查看|借阅功法 400001": 2, "查看|装配 400001": 1, "查看 400001": 0}
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

CHECKS = (
    ("标签不带 tone", check_labels_have_no_tone),
    ("链接文本无公式", check_rendered_links_are_plain),
    ("多分支解析", check_branches_resolve),
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
