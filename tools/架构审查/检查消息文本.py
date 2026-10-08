"""消息文本审查：**消息里不许出现 LaTeX**。

2026-10 起，Markdown（QQ）通道不再产生公式：客户端不渲染 `$...$`，包成公式的状态、进度、
强调与小字会原样露出源码（玩家看到的是「缺少目标」前面挂一串反斜杠命令）。
所以这条判据把三件事钉住：

1. **消息文本里没有 LaTeX 痕迹**（美元号、反斜杠命令、花括号、颜色值）；
2. **QQ 载荷是 markdown，且保持协议说明的引用层级**（标题一层、正文二层）——驱动器认不出消息
   就会整条当纯文本发，`> ` 会一起露出；同时载荷里同样不许有 LaTeX；
3. **后台网页对合成公式仍能降级**：`data-plain` 里不许留 LaTeX 痕迹。
   这一条现在守的是**韧性**而不是现状——消息里已经没有公式了，但后台那条投影仍能处理
   「万一哪条历史文本带了公式」的情形，所以保留并用合成输入验它。
4. **前端兜底优先用 `data-plain`**（静态查后台 `app.js`），改回直接印原文就红。

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
    BS + "text",
    BS + "small",
    BS + "large",
    BS + "textcolor",
    BS + ";",
    BS + "begin",
)
#: 可读文本里不该出现的东西（比上面多两个：花括号与颜色值）。
PLAIN_MARKS = LATEX_TRACES + ("{", "}", "#")
#: 合成公式：只用来验后台投影的降级还活着。
PLAIN_INPUTS = (
    BS + "small{" + BS + "textcolor{#27AE60}{" + BS + "text{空闲}}}",
    BS + "small{" + BS + "textcolor{#C0392B}{" + BS + "text{▰▰▰▰▰}}" + BS + "; " + BS + "textcolor{#C0392B}{" + BS + "text{332 / 332}}}",
)
SPAN_RE = re.compile(r'<span class="message-formula"([^>]*)>')
ATTR_RE = re.compile(r'data-([a-z]+)="([^"]*)"')


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


def check_console_degrades() -> list[str]:
    """后台投影对合成公式仍能给出干净的可读文本。"""

    presentation = _presentation()
    problems: list[str] = []
    for value in PLAIN_INPUTS:
        plain = presentation._formula_plain(value)
        if not plain:
            problems.append("转换结果为空：" + value)
            continue
        for mark in PLAIN_MARKS:
            if mark in plain:
                problems.append(f"可读文本里仍有 {mark}：{value} -> {plain}")
    content = "$" + BS + "small{" + BS + "text{一句}}$" + " 普通正文"
    html = presentation.render_message_html(
        SimpleNamespace(message_type="markdown", content=content, flow_id=1)
    )
    spans = SPAN_RE.findall(html)
    if not spans:
        problems.append("后台投影对合成公式没有产生公式 span，降级链路断了")
    for index, attributes in enumerate(spans, start=1):
        values = dict(ATTR_RE.findall(attributes))
        plain = values.get("plain", "")
        if not plain:
            problems.append(f"第 {index} 个公式没有可读文本")
            continue
        for mark in PLAIN_MARKS:
            if mark in plain:
                problems.append(f"第 {index} 个公式的可读文本仍像 LaTeX：{plain[:40]}")
    return problems


def check_frontend_uses_plain() -> list[str]:
    """前端兜底必须优先用 data-plain；改回直接印原文就红。"""

    text = (ROOT / "static" / "game-console" / "app.js").read_text(encoding="utf-8")
    fallbacks = text.count("node.textContent = ")
    good = text.count("node.textContent = node.dataset.plain || source;")
    problems: list[str] = []
    if good == 0:
        problems.append("app.js 的公式兜底没有用 data-plain")
    if fallbacks != good:
        problems.append(f"app.js 里还有 {fallbacks - good} 处兜底直接印原文")
    return problems


CHECKS = (
    ("消息文本没有 LaTeX", check_text_has_no_latex),
    ("QQ 载荷是 markdown 且没有 LaTeX", check_qq_payload),
    ("后台投影仍能降级", check_console_degrades),
    ("两条通道正文一致", check_channels_agree),
    ("前端优先用可读文本", check_frontend_uses_plain),
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
    print("消息文本审查通过：消息里没有 LaTeX，QQ 载荷是 markdown，后台降级仍活着")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
