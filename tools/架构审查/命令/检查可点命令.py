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

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from launch.adapter.qq_protocol import payload as qq_payload  # noqa: E402

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
    root = pathlib.Path(__file__).resolve().parents[3]
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
    root = pathlib.Path(__file__).resolve().parents[3]
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
    return qq_payload.payload_text(payload)


def check_rendered_links_are_plain() -> list[str]:
    """三种危险写法渲染出来，链接文本里都不许出现公式标记。"""

    from message import M

    hazard = M.command(M.text("透甲", tone="mystic"), "查看 400001")
    samples = {
        "带 tone 的标签": M.document().section("栏").line(hazard).build(),
        "纯文本标签": (
            M.document().section("栏")
            .line(M.command("透甲", "查看 400001")).build()
        ),
        "caption 行里的命令": (
            M.document().section("栏")
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



#: 用法里的占位词。一条命令的用法**全是**这些词，玩家就没有能照抄的例子。
USAGE_PLACEHOLDERS = (
    "编号", "名称", "品级", "数量", "页码", "槽位", "孔位",
    "角色名", "宗门名", "玩家", "目标", "或", "…", "<", ">",
)

#: 玩家可见文案（说明/结果）里的内部行话。
PLAYER_JARGON = ("原子", "事务", "幂等", "回滚", "序列化", "落库", "写库")


def check_usages_have_concrete_example() -> list[str]:
    """每条命令至少要有一个**能照抄的例子**。

    委托方 2026-10 指着帮助卡说：「炼阵 的说明写的不行」「下面的炼丹就写得很好」——
    `炼丹` 给了四个能照抄的例子（炼丹 / 炼丹 恢复丹 / 炼丹 战丹 2 / 炼丹 100005），
    而 `炼阵` 当时只有一行占位符，玩家照着敲一无所获。本判据就钉这一条：
    **整条命令的用法不能全是占位写法**（这与「用法例子能被自己受理」互补：那条只跑不带占位词的例子，
    全是占位词时它会整条跳过，于是这类命令长期没人管）。
    """

    problems: list[str] = []
    for path in sorted(GAME.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in USAGE_BLOCK.finditer(text):
            block = match.group(1)
            usages = re.findall(r'\"([^\"]+)\"|\'([^\']+)\'', block)
            items = [a or b for a, b in usages]
            if not items:
                continue
            concrete = [u for u in items if not any(p in u for p in USAGE_PLACEHOLDERS)]
            if concrete:
                continue
            line = text[: match.start()].count("\n") + 1
            where = path.relative_to(ROOT).as_posix() + ":" + str(line)
            problems.append(
                where + " 的用法全是占位写法，没有能照抄的例子：" + items[0].strip()[:60]
            )
    return problems


def check_player_copy_has_no_jargon() -> list[str]:
    """玩家可见的说明与结果不许出现内部行话。

    委托方 2026-10：帮助卡上「结果: 原子消耗兽宝、灵矿和灵植…」——「原子」是事务术语，玩家看不懂。
    同类真出过的还有「在同一事务中转移资产」。参考项目 `xiuxian3` 的富文本规则也写着：
    「不把数据库字段、内部 ID、配置名、异常栈写给普通玩家」。
    """

    problems: list[str] = []
    pattern = re.compile(r'\"(summary|side_effect)\"\s*:\s*\"([^\"]*)\"')
    for path in sorted(GAME.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            field, value = match.group(1), match.group(2)
            for word in PLAYER_JARGON:
                if word in value:
                    line = text[: match.start()].count("\n") + 1
                    where = path.relative_to(ROOT).as_posix() + ":" + str(line)
                    problems.append(
                        where + " 的 " + field + " 出现内部行话「" + word + "」：" + value[:50]
                    )
    return problems


def check_help_has_side_effect() -> list[str]:
    """每条命令的帮助都要有一句「结果」。

    委托方 2026-10 指着帮助卡：「其他命令你也都看看」。查下来 18 条命令（去重后 8 条）的帮助**根本没有「结果」这一行**，
    而同屏的 `炼丹`／`炼阵` 都有——卡上少一行，标准就不齐。玩家最想知道的恰恰是「我这一下会付出什么、东西去哪」。
    """

    problems: list[str] = []
    summary = re.compile(r'\"summary\"\s*:')
    for path in sorted(GAME.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in summary.finditer(text):
            # 帮助元数据的形状是 category/summary/usage/side_effect/order；
            # 只有后面跟着 usage 的 summary 才是帮助，别处（卡面说明等）不管。
            # 窗口到下一个 summary 为止：用法多的命令（宗门 11 条）会把 side_effect 推到很后面。
            rest = text[match.end():]
            nxt = rest.find('"summary"')
            if nxt >= 0:
                rest = rest[:nxt]
            tail = rest.split("\n")
            if not any("usage" in line for line in tail):
                continue
            if not any("side_effect" in line for line in tail):
                line = text[: match.start()].count("\n") + 1
                where = path.relative_to(ROOT).as_posix() + ":" + str(line)
                problems.append(where + " 的帮助没有「结果」（side_effect）")
    return problems


def check_inline_commands_do_not_submit() -> list[str]:
    """行内命令链接（无边框按钮）一律只填入，不直接发。

    委托方 2026-10 纠正我的实现：「所有的无边框按钮都是点击之后**不发**的，有的需要补充参数，有的需要删改」，
    点了就发容易出错。所以 `M.command` 的默认值必须是「只填入」，玩家侧也不许出现 `submit=True`。
    注意区分：底部结构化按钮（`Action`）该发就发，不受这条管。
    """

    problems: list[str] = []
    for rel, label in (
        ("message/builder.py", "M.command"),
        ("message/schema.py", "CommandLink"),
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        if "submit: bool = False" not in text:
            problems.append(rel + " 的 " + label + " 默认不是「只填入」（submit 必须默认 False）")
    for path in sorted(GAME.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").replace(chr(13), "").split(chr(10)), start=1):
            if line.lstrip().startswith("#"):
                continue
            if "submit=True" in line or "submit=is_complete" in line:
                where = path.relative_to(ROOT).as_posix() + ":" + str(number)
                problems.append(where + " 行内按钮点击即发：" + line.strip()[:56])
    return problems



def check_icons_are_registered() -> list[str]:
    """卡片上用到的图标分类都必须在 `message/icons.py` 的注册表里。

    2026-10 上线实测栽过一次：`game/cmd/通用.兑换码/reply.py` 写 `icon="gift"`，而图标表里没有 `gift`——
    玩家第一次兑换就崩在 `render_markdown` → `icon_for` 的 `KeyError`，服务不挂但回复发不出去。
    这类「字面量没登记」的眼漏，靠读代码很难发现，所以按字面量逐个核对。
    """

    import message.icons as icons

    import game.app  # noqa: F401  # 触发游戏侧的图标注册（若有）

    known = set(icons.SECTION_ICONS)
    pattern = re.compile(r'icon\s*=\s*[\'"]([A-Za-z0-9_.-]+)[\'\"]')
    problems: list[str] = []
    for base in ("game", "launch", "message", "static"):
        for path in sorted((ROOT / base).rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".js", ".html"):
                continue
            if "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in pattern.finditer(text):
                key = match.group(1)
                if key not in known:
                    line = text[: match.start()].count(chr(10)) + 1
                    problems.append(f"{path.relative_to(ROOT).as_posix()}:{line} 用了没登记的图标分类「{key}」")
    return problems

def check_paging_buttons_avoid_hosting_commands() -> list:
    """名称含「页」的按钮，其命令不得指向带 hosting 元数据的命令。

    托管中的玩法命令要过 authorize_execution，而它要求请求号等于托管记录里的那一次；
    玩家手点翻页时请求号是新的，于是点了没反应（2026-10-14 探险实测）。翻页是只读的，
    应当走不带 hosting 元数据的独立入口。
    """

    带托管: set = set()
    for path in GAME.rglob("__init__.py"):
        text = path.read_text(encoding="utf-8")
        if '"hosting"' not in text:
            continue
        for match in re.finditer(r'cmd=(\([^)]*\)|"[^"]*")([\s\S]{0,900}?)"hosting"', text):
            names = re.findall(r'"([^"]+)"', match.group(1))
            if names:
                带托管.add(names[0])

    def 走(node: object, 命中: list) -> None:
        if isinstance(node, dict):
            if "命令" in node:
                命中.append(node)
            for value in node.values():
                走(value, 命中)
        elif isinstance(node, list):
            for value in node:
                走(value, 命中)

    problems: list = []
    for path in (ROOT / "data").rglob("*.json"):
        if "按钮" not in path.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        命中: list = []
        走(data, 命中)
        for 条目 in 命中:
            名称 = str(条目.get("名称") or "")
            命令 = str(条目.get("命令") or "")
            首个 = 命令.split()
            if "页" in 名称 and 首个 and 首个[0] in 带托管:
                problems.append(
                    f"{path.relative_to(ROOT)} 的「{名称}」按钮发的是带 hosting 的命令「{命令}」"
                    "——托管中会被守卫拦下（手点请求号对不上），翻页请指向不带 hosting 的只读命令"
                )
    return problems


CHECKS = (
    ("标签不带 tone", check_labels_have_no_tone),
    ("链接文本无公式", check_rendered_links_are_plain),
    ("多分支解析", check_branches_resolve),
    ("按钮目标已注册", check_commands_are_registered),
    ("按钮数据命令已注册", check_button_data_commands_are_registered),
    ("翻页按钮不带托管命令", check_paging_buttons_avoid_hosting_commands),
    ("地点面板只许位置/行路取", check_location_panel_callers),
    ("翻页页必须有返回", check_paged_pages_have_way_back),
    ("用法不露机器词", check_usages_have_no_machine_words),
    ("用法要有能照抄的例子", check_usages_have_concrete_example),
    ("玩家文案不露行话", check_player_copy_has_no_jargon),
    ("帮助要有结果", check_help_has_side_effect),
    ("行内按钮只填入", check_inline_commands_do_not_submit),
    ("图标分类都已登记", check_icons_are_registered),
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
