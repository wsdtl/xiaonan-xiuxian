"""战报页的静态资源判据：这一类错误不能再靠人肉发现。

战报页挂在 `/battle/<编号>` 下，页面里的资源**必须用绝对路径**。相对路径会被解析成
`/battle/…`，而那条路径被战报路由的兜底抓走、回的是 HTML —— 浏览器严格 MIME 检查一拒，
整个模块图断链，页面就只剩空壳（没有 UI）。这条坑已经踩过三次：

1. `index.html` 的 `./style.css` / `./app.js`；
2. `app.js` 的 `./timeline.js` / `./ui.js`；
3. `timeline.js` 的 `./ui.js`。

所以判据有两条：**不许出现相对引用**、**引用的每个地址都真的取得到**（前者防复发，后者防改名）。
"""
from __future__ import annotations

import pathlib
import re

静态目录 = pathlib.Path(__file__).resolve().parents[1] / "static" / "battle-report"

#: 页面与模块里所有「从别处取东西」的写法。
引用模式 = re.compile(r'(?:href|src)\s*=\s*"([^"]+)"|from\s+"([^"]+)"')


def 收集引用() -> list[tuple[str, int, str]]:
    引用: list[tuple[str, int, str]] = []
    for 文件 in sorted(静态目录.glob("*")):
        if 文件.suffix not in {".html", ".js", ".css"}:
            continue
        for 行号, 行 in enumerate(文件.read_text(encoding="utf-8").splitlines(), 1):
            for 匹配 in 引用模式.finditer(行):
                地址 = 匹配.group(1) or 匹配.group(2)
                引用.append((文件.name, 行号, 地址))
    return 引用


def test_report_page_assets_are_absolute() -> None:
    """页面与模块之间的引用一律走 `/static/battle-report/…`，不许相对路径。"""

    相对 = [
        (文件, 行号, 地址)
        for 文件, 行号, 地址 in 收集引用()
        if not 地址.startswith("/static/") and not 地址.startswith("http")
    ]
    assert not 相对, (
        "战报页在 /battle/<编号> 下，相对引用会被解析成 /battle/… 并被战报路由吞成 HTML："
        + "；".join(f"{文件}:{行号} {地址}" for 文件, 行号, 地址 in 相对)
    )


def test_every_referenced_asset_exists() -> None:
    """引用的每个地址都要在静态目录里真的有那个文件（改名/搬家后立刻红）。"""

    缺失 = []
    for 文件, 行号, 地址 in 收集引用():
        if not 地址.startswith("/static/battle-report/"):
            continue
        目标 = 静态目录 / 地址[len("/static/battle-report/") :]
        if not 目标.is_file():
            缺失.append(f"{文件}:{行号} {地址}")
    assert not 缺失, "引用的静态资源不存在：" + "；".join(缺失)


def test_report_page_has_exactly_one_module_entry() -> None:
    """页面只许有一个模块入口，且它必须存在——避免再出现"半套资源"的页面。"""

    html = (静态目录 / "index.html").read_text(encoding="utf-8")
    模块 = re.findall(r'<script[^>]+type="module"[^>]+src="([^"]+)"', html)
    assert 模块 == ["/static/battle-report/app.js"], 模块
    assert (静态目录 / "app.js").is_file()
