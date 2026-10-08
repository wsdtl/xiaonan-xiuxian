"""静态资源审查：前端页面、样式与页面策略的形状。

`static/` 一直是**判据的空白区**：`game/`、`data/`、`tools/` 都有对应的审查，而前端页面
一条都没有。代价在第 85 轮盘点时露了出来：同一个页面的 CSS 挂着 `?v=2`、JS 挂着 `?v=20`，
`?v=20` 还得在 `import "./ui.js?v=20"` 里再写一遍（五处手工同步，漏一处就是老模块配新模块）；
一份样式里躺着三处没人建立的类；后台页面下发的脚本来源**完全没有内容安全策略**，
而它恰恰是能执行游戏命令的入口；KaTeX 从 CDN 取，改了内容也照加载。

这条检查把这几件事变成可执行判据：

1. **不许再出现手工版本号**：`static/` 下任何 `?v=<数字>` 都算违规。缓存由 `/static` 的
   `no-cache` + ETag 管（见 `launch/mount.py` 的 `NoCacheStaticFiles`），内容一变
   ETag 就变，人不必记版本号。
2. **页面基本形状**：每个应用的 `index.html` 要有 `lang="zh-CN"`、非空标题、viewport，
   并引用本应用的 `style.css`。
3. **跨源资源必须带 `integrity` 与 `crossorigin`**：CDN 上的内容改了就加载不出来。
4. **不许内联脚本与内联样式**：页面的 CSP 不含 `script-src 'unsafe-inline'`，
   内联 `<script>` 会被浏览器直接拒绝——那比报错更安静。
5. **没有孤儿资源**：应用目录下的每个 `.css`/`.js` 都要被页面或模块引用到。
6. **没有死样式**：`style.css` 里的每个类名都要在该应用的语料里出现过，
   或者由模板前缀拼出来（`tone-${…}`、`zoom-${…}`、`depth-${…}` 这类算活）。
7. **下发页面的路由要有 CSP**：凡是 `HTMLResponse` 的 `site.py`，头部里必须有
   `Content-Security-Policy`。

**判据宁可漏报也不误伤**：第 6 条的语料取「该应用自己的 `static/` + 全部 `game`/`launch`/`data`」。
口径放宽的代价是「别的应用用过的类名在这个应用里不算死」，换来的是一条不会天天乱叫的检查。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查静态资源.py

**退出码：0 = 干净，1 = 有违规**（列出文件与行号）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "static"

#: 前端应用，与 `static/` 下的目录一一对应。
APPS = ("baike", "battle-report", "game-console", "world-map", "zhuangpei")

#: 类名「活没活」的语料范围：服务端任何可能吐出类名的地方。
CORPUS_ROOTS = ("game", "launch", "data")
CORPUS_SUFFIXES = {".py", ".js", ".json", ".html", ".css"}
#: 应用目录内部参与「谁被引用」判定的后缀。
ASSET_SUFFIXES = {".js", ".css"}

SKIP_PARTS = {"__pycache__", ".venv", ".git", "node_modules"}

VERSION_QUERY = re.compile(r"\?v=\d+")
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<(link|script)\b([^>]*)>", re.IGNORECASE)
STYLE_BLOCK_RE = re.compile(r"<style\b", re.IGNORECASE)
SELECTOR_RE = re.compile(r"([^{}]+)\{")
CLASS_RE = re.compile(r"\.([A-Za-z_][\w-]*)")
IMPORT_RE = re.compile(r"""(?:from|import)\s*\(?\s*["']([^"']+)["']""")
EXTERNAL_RE = re.compile(r"^(?:https?:)?//", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    rule: str
    path: Path
    line: int
    detail: str

    def render(self) -> str:
        return f"[{self.rule}] {self.path}:{self.line}  {self.detail}"


def _relative(path: Path) -> Path:
    try:
        return path.relative_to(PROJECT_ROOT)
    except ValueError:
        return path


def _app_dir(app: str) -> Path:
    return STATIC_DIR / app


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _app_texts(app: str) -> list[Path]:
    """应用目录下的全部文件（含子目录：以后把脚本分文件夹也照样算）。"""

    folder = _app_dir(app)
    if not folder.is_dir():
        return []
    return [
        path
        for path in sorted(folder.rglob("*"))
        if path.is_file() and not SKIP_PARTS & set(path.parts)
    ]


def _corpus(app: str) -> str:
    """该应用的语料：自己目录里的**页面与脚本** + 服务端全部可能吐类名的地方。

    **本应用自己的 `style.css` 不算语料**——它正是被查的对象。第一版把它算了进去，
    于是每个类名都能在「定义它的那份样式」里找到自己，`check_dead_css` 永远通过：
    一个查不出东西的检查比没有检查更让人放心。这条是反向验证抓出来的。
    """

    chunks: list[str] = []
    for path in _app_texts(app):
        if path.suffix in {".js", ".html"}:
            chunks.append(_read(path))
    for root in CORPUS_ROOTS:
        for path in (PROJECT_ROOT / root).rglob("*"):
            if not path.is_file() or path.suffix not in CORPUS_SUFFIXES:
                continue
            if SKIP_PARTS & set(path.parts):
                continue
            try:
                chunks.append(_read(path))
            except (OSError, UnicodeDecodeError):
                continue
    return "\n".join(chunks)


def check_no_version_query() -> list[Finding]:
    findings: list[Finding] = []
    for app in APPS:
        for path in _app_dir(app).rglob("*"):
            if not path.is_file() or path.suffix not in CORPUS_SUFFIXES:
                continue
            text = _read(path)
            for match in VERSION_QUERY.finditer(text):
                findings.append(
                    Finding(
                        "手工版本号",
                        _relative(path),
                        _line_of(text, match.start()),
                        f"`{match.group(0)}` 要人记两处才不出错；缓存交给 /static 的 "
                        f"`no-cache` + ETag，删掉它",
                    )
                )
    return findings


def check_page_shape() -> list[Finding]:
    findings: list[Finding] = []
    for app in APPS:
        path = _app_dir(app) / "index.html"
        if not path.is_file():
            findings.append(Finding("页面形状", _relative(path), 0, "应用目录里没有 index.html"))
            continue
        text = _read(path)
        relative = _relative(path)
        if 'lang="zh-CN"' not in text:
            findings.append(Finding("页面形状", relative, 1, '缺 `lang="zh-CN"`'))
        title = TITLE_RE.search(text)
        if title is None:
            findings.append(Finding("页面形状", relative, 1, "缺 `<title>`"))
        elif not title.group(1).strip():
            findings.append(
                Finding("页面形状", relative, _line_of(text, title.start()), "标题是空的")
            )
        if 'name="viewport"' not in text:
            findings.append(Finding("页面形状", relative, 1, '缺 `<meta name="viewport">`'))
        if "style.css" not in text:
            findings.append(Finding("页面形状", relative, 1, "没有引用本应用的 style.css"))
    return findings


def check_external_integrity() -> list[Finding]:
    findings: list[Finding] = []
    for app in APPS:
        path = _app_dir(app) / "index.html"
        if not path.is_file():
            continue
        text = _read(path)
        for tag, attrs in TAG_RE.findall(text):
            source = re.search(r'(?:src|href)\s*=\s*"([^"]*)"', attrs)
            if source is None or not EXTERNAL_RE.match(source.group(1).strip()):
                continue
            missing = [
                name for name in ("integrity", "crossorigin") if name not in attrs
            ]
            if missing:
                findings.append(
                    Finding(
                        "跨源资源无校验",
                        _relative(path),
                        _line_of(text, text.find(attrs)),
                        f"`{source.group(1)}` 缺 {'、'.join(f'`{name}`' for name in missing)}"
                        f"：CDN 上的内容被改也会照常加载",
                    )
                )
    return findings


def check_no_inline_code() -> list[Finding]:
    findings: list[Finding] = []
    for app in APPS:
        path = _app_dir(app) / "index.html"
        if not path.is_file():
            continue
        text = _read(path)
        for match in SCRIPT_RE.finditer(text):
            if match.group(2).strip():
                findings.append(
                    Finding(
                        "内联脚本",
                        _relative(path),
                        _line_of(text, match.start()),
                        "页面 CSP 不含 `unsafe-inline`，这段内联脚本会被浏览器静默拒绝",
                    )
                )
        inline_style = STYLE_BLOCK_RE.search(text)
        if inline_style is not None:
            findings.append(
                Finding(
                    "内联样式",
                    _relative(path),
                    _line_of(text, inline_style.start()),
                    "样式放 style.css，页面的 CSP 只放开 'self' 与 KaTeX 的 CDN",
                )
            )
    return findings


def check_orphan_assets() -> list[Finding]:
    """应用目录下的每个 js/css 都得有人引用。"""

    findings: list[Finding] = []
    for app in APPS:
        folder = _app_dir(app)
        texts = {
            path.name: _read(path)
            for path in _app_texts(app)
            if path.suffix in {".js", ".html"}
        }
        for path in _app_texts(app):
            if path.suffix not in ASSET_SUFFIXES:
                continue
            referenced = False
            for name, text in texts.items():
                if name == path.name:
                    continue
                if path.name in text:
                    referenced = True
                    break
                if path.name in IMPORT_RE.findall(text):
                    referenced = True
                    break
            if not referenced:
                findings.append(
                    Finding(
                        "孤儿资源",
                        _relative(path),
                        1,
                        "没有任何页面或模块引用它",
                    )
                )
    return findings


def _is_live_class(name: str, corpus: str) -> bool:
    """类名算「活」的两种方式：语料里出现过，或由模板前缀拼出来。

    拼出来的有两种写法：前端 `` `tone-${tone}` ``，后端 f-string
    ``f'<div class="message-quote depth-{min(depth, 3)}">'``。两种都要认——
    只认前端那种时，`.depth-2`、`.depth-3` 会被当成死样式（反向验证抓出来的）。
    """

    if name in corpus:
        return True
    parts = name.split("-")
    for size in range(1, len(parts)):
        prefix = "-".join(parts[:size])
        if f"{prefix}-${{" in corpus or f"{prefix}-{{" in corpus:
            return True
    return False


def check_dead_css() -> list[Finding]:
    findings: list[Finding] = []
    for app in APPS:
        path = _app_dir(app) / "style.css"
        if not path.is_file():
            continue
        css = _read(path)
        corpus = _corpus(app)
        reported: set[str] = set()
        for match in SELECTOR_RE.finditer(css):
            for name in CLASS_RE.findall(match.group(1)):
                if name in reported or _is_live_class(name, corpus):
                    continue
                reported.add(name)
                findings.append(
                    Finding(
                        "死样式",
                        _relative(path),
                        _line_of(css, match.start(1)),
                        f"`.{name}` 全工程没有任何地方建立它（模板拼出来的算活）",
                    )
                )
    return findings


def check_page_routes_csp() -> list[Finding]:
    findings: list[Finding] = []
    for path in (PROJECT_ROOT / "game" / "cmd").rglob("site.py"):
        if SKIP_PARTS & set(path.parts):
            continue
        text = _read(path)
        if "HTMLResponse" not in text or "Content-Security-Policy" in text:
            continue
        findings.append(
            Finding(
                "页面无 CSP",
                _relative(path),
                1,
                "这个模块下发 HTML 却没有内容安全策略",
            )
        )
    return findings


CHECKS = (
    ("手工版本号", check_no_version_query),
    ("页面形状", check_page_shape),
    ("跨源资源无校验", check_external_integrity),
    ("内联脚本", check_no_inline_code),
    ("孤儿资源", check_orphan_assets),
    ("死样式", check_dead_css),
    ("页面无 CSP", check_page_routes_csp),
)


def main() -> int:
    findings: list[Finding] = []
    for name, check in CHECKS:
        try:
            findings.extend(check())
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(Finding(name, Path("static"), 0, f"读取失败：{exc}"))
    if not findings:
        print(f"静态资源审查通过：{len(CHECKS)} 项检查")
        return 0
    print(f"静态资源违规 {len(findings)} 处：")
    for finding in sorted(findings, key=lambda item: (item.rule, str(item.path), item.line)):
        print(f"  {finding.render()}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
