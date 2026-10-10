"""消息文本审查：**消息里不许出现 LaTeX**。

2026-10 起，Markdown（QQ）通道不再产生公式：客户端不渲染 `$...$`，包成公式的状态、进度、
强调与小字会原样露出源码（玩家看到的是「缺少目标」前面挂一串反斜杠命令）。
所以这条判据把三件事钉住：

1. **消息文本里没有 LaTeX 痕迹**（美元号、反斜杠命令、花括号、颜色值）；
2. **QQ 载荷是 markdown，且保持协议说明的引用层级**（标题一层、正文二层）——驱动器认不出消息
   就会整条当纯文本发，`> ` 会一起露出；同时载荷里同样不许有 LaTeX；
3. **后台页面与 QQ 载荷必须是同一份正文**（委托方 2026-10 口径：两条通道统一）。
   归一化后逐字比较：块级标签、markdown 链接、任意层引用标记都要剥掉再比。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查消息文本.py

**退出码：0 = 干净，1 = 有违规。**
"""

from __future__ import annotations

import pathlib
import re
import sys
from types import SimpleNamespace

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from message import M  # noqa: E402
from message.renderers.markdown import (  # noqa: E402
    render_markdown,
    render_rich_markdown,
)

BS = chr(92)
#: 消息文本与 QQ 载荷里都不该出现的东西。
LATEX_TRACES = (
    "$",
    BS + "small",
    BS + "large",
    BS + "textcolor",
    BS + ";",
    BS + "begin",
)



def _presentation():
    import game.cmd.后台.天道后台.presentation as module

    return module


def sample_message() -> object:
    """一条把消息构造器都用上的样例：状态、进度、小字、强调、命令、字段、列表、图片。"""

    builder = M.document()
    builder.section("身份", icon="status").line(M.status("空闲", tone="positive"), " 修士")
    builder.field("血气", M.progress(332, 332))
    builder.line(M.text("强调的名字", tone="emphasis"), " 与普通文字")
    builder.small("每五分钟完成一轮")
    builder.item(1, M.command("查看 400001", "查看 400001", submit=False))
    builder.note("附注一句")
    return builder.build()


def sample_document() -> str:
    """样例消息渲染出来的正文。"""

    document = sample_message().document
    return render_markdown(
        document, command_renderer=lambda link, *_args: render_rich_markdown(link.label)
    )


def check_text_has_no_latex() -> list[str]:
    """消息文本里没有 LaTeX 痕迹。"""

    text = sample_document()
    return [
        f"消息文本里出现 {trace!r}：{line.strip()[:60]}"
        for line in text.splitlines()
        for trace in LATEX_TRACES
        if trace in line
    ]


def check_qq_payload() -> list[str]:
    """QQ 出口是 markdown、保持引用层级，且同样没有 LaTeX。"""

    from launch.adapter.qq_protocol.render import render_qq_message

    payload = render_qq_message(sample_message())
    if not isinstance(payload, dict):
        return ["QQ 载荷不是驱动器协议对象，会被当纯文本发"]
    problems: list[str] = []
    if str(payload.get("kind")) != "markdown":
        problems.append("QQ 载荷 kind 不是 markdown：" + str(payload.get("kind")))
    content = str((payload.get("markdown") or {}).get("content") or "")
    lines = [line for line in content.splitlines() if line.strip()]
    if not any(line.startswith("> > ") for line in lines):
        problems.append("正文没有二层引用")
    if not any(line.startswith("> ") and not line.startswith("> > ") for line in lines):
        problems.append("标题没有一层引用")
    for line in lines:
        for trace in LATEX_TRACES:
            if trace in line:
                problems.append(f"QQ 载荷里出现 {trace!r}：{line.strip()[:60]}")
    return problems


def _visible(text: str) -> str:
    """剥掉各端的皮，只留玩家看到的正文。"""

    import html as html_module

    # 块级边界先变成换行，否则撕掉标签后整条会粘成一句。
    stripped = re.sub("</(?:div|p|li|h[1-6])>|<br\\s*/?>", "\n", str(text or ""))
    stripped = re.sub("<[^>]+>", "", stripped)
    # Markdown 链接只留文字：QQ 那端是 [文字](mqqapi://…)，后台那端已是纯文字。
    stripped = re.sub("\\[([^\\]]*)\\]\\([^)]*\\)", "\\1", stripped)
    stripped = html_module.unescape(stripped).replace("**", "")
    lines: list[str] = []
    for line in stripped.splitlines():
        # 引用层级各端表达不同：QQ 是任意层 `> `，后台是块级元素；这里一律剥掉。
        line = re.sub("^(?:\\s*>\\s*)+", "", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def check_markup_escaped() -> list[str]:
    """动态文本里的 Markdown 标点必须转义——玩家名带着 * 或 _ 不能破坏消息结构。"""

    builder = M.document().section("身份", icon="status").line("名字 *_a_[b]_ $x$ 尾巴")
    text = render_markdown(builder.build().document)
    problems: list[str] = []
    for token in ("*", "_", "$"):
        if ("\\" + token) not in text:
            problems.append(f"Markdown 标点 {token} 没有被转义：{text.strip()[:60]}")
    return problems


def check_channels_agree() -> list[str]:
    """后台页面与 QQ 载荷必须是同一份正文。"""

    from launch.adapter.qq_protocol.render import render_qq_message

    message = sample_message()
    content = sample_document()
    payload = render_qq_message(message)
    qq = str((payload.get("markdown") or {}).get("content") or "")
    html = _presentation().render_message_html(
        SimpleNamespace(message_type="markdown", content=content, flow_id=1)
    )
    problems: list[str] = []
    if _visible(qq) != _visible(html):
        problems.append("两条通道正文不一致 QQ=" + repr(_visible(qq)[:70]) + " 页面=" + repr(_visible(html)[:70]))
    if _visible("甲") == _visible("乙"):
        problems.append("比较器分不出不同文本，判据等于没跑")
    return problems


def check_mention_keeps_body() -> list[str]:
    """补 @ 之后，正文必须与不补 @ 时**逐字相同**。

    称呼是在 QQ 驱动层贴上去的（业务层看不到），所以别的判据都照不到它——
    真出过事：称呼紧贴正文时，正文以 `>`／`#` 开头的卡（宗门那张）控制符不在行首，
    整张卡版式散掉。这里对几种典型开头分别验一遍：去掉称呼必须还原成原文。
    """

    from launch.adapter.context import MENTION_SENDER, SendOptions
    from launch.adapter.qq_protocol.manager import QqReplyManager as QM

    class _Target:
        is_group = True
        user_id = "U1"

    problems: list[str] = []
    samples = (
        ("以标题开头", "# 宗门\n> ✨ 宗门"),
        ("以引用开头", "> 🗺️ 山河\n> > [1] 溪隐台"),
        ("以加粗开头", "**晓楠修仙**\n> ✨ 帮助"),
        ("以列表开头", "- 一\n- 二"),
        ("多行普通文本", "第一行\n第二行"),
    )
    for label, body in samples:
        message = {"kind": "markdown", "content": body, "image": None, "actions": ()}
        plain = str((QM._markdown_payload(message).get("markdown") or {}).get("content"))
        decorated = str(
            (
                QM._apply_mention(
                    QM._markdown_payload(message),
                    _Target(),
                    SendOptions(mention=MENTION_SENDER),
                ).get("markdown")
                or {}
            ).get("content")
        )
        # 称呼可能是紧贴（`<@U1>正文`）或单独一行（`<@U1>\n正文`），两种都要还原。
        stripped = decorated
        for prefix in ("<@U1>\n", "<@U1>"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):]
                break
        if stripped != plain:
            problems.append(
                f"{label}：补上称呼后正文被改动（{plain[:24]!r} → {stripped[:24]!r}）"
            )
    return problems


def check_format_lines_follow_rule() -> list[str]:
    """「格式：」文案的多用法记法必须统一。

    真出过事：一条命令七八种用法挤成一行斜杠串，读的人得自己数。约定：
    ` / ` 分隔不同用法（渲染器会把换行拍平，只能一行一句地铺），
    用法内部用 `|` 表示二选一、`[]` 表示可选，不要再写「，或：」这类口语连接，
    单段不超过 40 字。
    """

    import json

    root = pathlib.Path(__file__).resolve().parents[2]
    problems: list[str] = []

    def walk(node: object, path: str = ""):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and "格式" in value:
                    yield path + "/" + str(key), value
                else:
                    yield from walk(value, path + "/" + str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from walk(value, f"{path}/{index}")

    for path in sorted((root / "data").rglob("*.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 不是 JSON 的数据文件跳过
            continue
        for key, text in walk(body):
            where = path.relative_to(root).as_posix() + key
            if "，或：" in text:
                problems.append(f"{where} 用了「，或：」连接：{text[:40]}")
            for part in text.split(" / "):
                if len(part) > 40:
                    problems.append(f"{where} 单段过长（{len(part)} 字）：{part[:40]}")
    return problems


CHECKS = (
    ("消息文本没有 LaTeX", check_text_has_no_latex),
    ("Markdown 标点已转义", check_markup_escaped),
    ("QQ 载荷是 markdown 且没有 LaTeX", check_qq_payload),
    ("两条通道正文一致", check_channels_agree),
    ("补 @ 不改动正文", check_mention_keeps_body),
    ("格式文案记法统一", check_format_lines_follow_rule),
)


def main() -> int:
    failed = 0
    for label, check in CHECKS:
        problems = check()
        if problems:
            failed += 1
            print(f"  [{len(problems)} 处] {label}")
            for line in problems[:6]:
                print("        " + line)
        else:
            print(f"  [干净] {label}")
    if failed:
        print(f"消息文本审查失败：{failed} 项")
        return 1
    print("消息文本审查通过：LaTeX/转义/载荷/通道/@/格式记法 全部干净")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
