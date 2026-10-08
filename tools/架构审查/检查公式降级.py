r"""公式降级审查：后台网页的每个公式都得带一份玩家看得懂的可读文本。

后台网页的公式（进度条、短状态、可点击名称、显式小字）由服务端投影成一段 KaTeX
源码，交给浏览器里的 KaTeX 渲染。问题是 **KaTeX 没加载出来时**（CDN 被拦、脚本没
执行、时序没对上）前端只能退回原始文本——那时候玩家看到的是

    行为: $\small{\textcolor{#27AE60}{\text{空闲}}}$

而不是「空闲」。这条判据把降级钉住：

- 公式 span **必须带非空的 `data-plain`**，取不到就说明前端只能吐 LaTeX；
- `data-plain` 里**不许再留 LaTeX 痕迹**（反斜杠、美元号、花括号、# 颜色值）；
- **QQ 出口必须是 markdown**，并保持协议说明第 98 行的引用层级（标题一层、正文二层）；驱动器认不出消息就会整条当纯文本发，`> ` 与公式会一起原样露出。
- 前端兜底**必须优先用 `data-plain`**（静态查 `app.js`），改回直接印原文就红。

语料不取某个角色的页面，而是**直接用消息构造器造公式**——公式的唯一来源就是
`M.status` / `M.progress` / `M.small` / `M.command`，所以判据不依赖
数据库、不依赖某个角色恰好有公式，跑起来也不到一秒。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查公式降级.py

**退出码：0 = 全部有可读文本，1 = 有公式降级不了。**
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

#: 取 `<span class="message-formula" ...>` 里的属性串。
SPAN_RE = re.compile(r'<span class="message-formula"([^>]*)>')
ATTR_RE = re.compile(r'data-([a-z]+)="([^"]*)"')
#: 可读文本里不该出现的东西。
LATEX_MARKS = ("\\", "$", "{", "}", "#")
PLAIN_INPUTS = (
    r"\small{\textcolor{#27AE60}{\text{空闲}}}",
    r"\small{\textcolor{#C0392B}{\text{▰▰▰▰▰}}\;\textcolor{#C0392B}{\text{332 / 332}}}",
    r"\large{\textcolor{#1E6A55}{\text{邓晓楠}}}",
    r"\small{\text{每五分钟完成一轮}}",
)


def _presentation():
    import game.cmd.后台.天道后台.presentation as module

    return module


def sample_message() -> object:
    """造一条带公式的消息对象（业务层交给驱动器的东西）。"""

    builder = M.document()
    builder.section("身份", icon="status").line(M.status("空闲", tone="positive"), " 修士")
    builder.field("血气", M.progress(332, 332))
    builder.small("每五分钟完成一轮")
    builder.line(M.command("查看 400001", "查看 400001", submit=False))
    return builder.build()


def sample_document() -> str:
    """造一份带公式的正文：状态徽章、进度条、显式小字、可点击名称各来一个。"""

    return render_markdown(

        sample_message().document, command_renderer=lambda link, *_args: render_rich_markdown(link.label)
    )

def check_plain_converter() -> list[str]:
    """转换器本身：挑几个真实形态，看可读文本是不是干净。"""

    plain_of = _presentation()._formula_plain
    problems: list[str] = []
    for value in PLAIN_INPUTS:
        plain = plain_of(value)
        if not plain:
            problems.append("转换结果为空：" + value)
            continue
        for mark in LATEX_MARKS:
            if mark in plain:
                problems.append(f"可读文本里仍有 {mark}：{value} -> {plain}")
    return problems


def check_spans_carry_plain() -> list[str]:
    """真实投影出来的公式 span 都要带干净的可读文本。"""

    content = sample_document()
    html = _presentation().render_message_html(
        SimpleNamespace(message_type="markdown", content=content, flow_id=1)
    )
    problems: list[str] = []
    spans = SPAN_RE.findall(html)
    if not spans:
        problems.append("投影里一个公式都没有，判据等于没跑")
    for index, attributes in enumerate(spans, start=1):
        values = dict(ATTR_RE.findall(attributes))
        latex = values.get("latex", "")
        plain = values.get("plain", "")
        if not latex:
            problems.append(f"第 {index} 个公式没有 data-latex")
        if not plain:
            problems.append(f"第 {index} 个公式没有可读文本：{latex[:40]}")
            continue
        for mark in LATEX_MARKS:
            if mark in plain:
                problems.append(f"第 {index} 个公式的可读文本仍像 LaTeX：{plain[:40]}")
    # 样例里特意留了一个可点命令：按消息协议说明第 115 行「可点名称不进公式」，
    # 它本来就该渲染成链接而不是公式，所以这里的期望值是 3（状态 / 进度 / 显式小字）。
    if len(spans) < 3:
        problems.append(f"投影里只有 {len(spans)} 个公式，样例覆盖不足")
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


def check_qq_payload_shape() -> list[str]:
    """QQ 出口必须是 markdown，并保持协议说明第 98 行的引用层级（标题一层、正文二层）。"""

    from launch.adapter.qq_protocol.render import render_qq_message

    payload = render_qq_message(sample_message())
    problems: list[str] = []
    if not isinstance(payload, dict):
        # 走到 manager 的 else 分支就是整条当纯文本发，> 与 $ 都会原样露出。
        return ["QQ 载荷不是驱动器协议对象，会被当纯文本发"]
    if str(payload.get("kind")) != "markdown":
        problems.append("QQ 载荷 kind 不是 markdown：" + str(payload.get("kind")))
    content = str((payload.get("markdown") or {}).get("content") or "")
    lines = [line for line in content.splitlines() if line.strip()]
    if not any(line.startswith("> > ") for line in lines):
        problems.append("正文没有二层引用")
    if not any(line.startswith("> ") and not line.startswith("> > ") for line in lines):
        problems.append("标题没有一层引用")
    return problems

CHECKS = (
    ("可读文本转换", check_plain_converter),
    ("公式都带可读文本", check_spans_carry_plain),
    ("前端优先用可读文本", check_frontend_uses_plain),
    ("QQ 出口是 markdown 且保持引用层级", check_qq_payload_shape),
)


def main() -> int:
    problems: list[str] = []
    for name, check in CHECKS:
        found = check()
        problems.extend(found)
        print(f"  [{'干净' if not found else str(len(found)) + ' 处'}] {name}")
        for item in found[:6]:
            print("     " + item)
    if problems:
        print(f"公式降级 {len(problems)} 处")
        return 1
    print(f"公式降级审查通过：{len(CHECKS)} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
