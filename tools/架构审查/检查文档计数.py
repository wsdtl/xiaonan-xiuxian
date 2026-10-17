"""文档计数审查：README 与 `tools/说明.md` 里写死的数目，必须与现状一致。

第 87 轮盘点基座时发现的：`README.md` 的「正式 JSON **1851 文档、5844 实体**」停在很早
以前（实际 1750 / 3932），`tools/说明.md` 的「共 **123 支脚本**：… `架构审查/` 16」也停在
第 84 轮（实际 124 支、架构审查 18 支），而「必过 23 项 / 全量 33 项」停在第 84 轮
（实际 25 / 35）。**这几处谁也不跑、谁也不数**，于是只能靠人偶然发现——而 `工具说明.md`
的同一份文档里恰好写着「条数写进名字就会漂」这条教训。这条判据把「数一遍」变成可执行动作。

判据只管**能从文件系统与代码数出来的数**：

- README：`game/core` 与 `game/features` 的微服务目录数、`game/cmd` 三个二级目录、
  `data` 的大类数与 `读取规则.json` 的组件数、JSON 文档/实体/资源池数、注册命令与守卫数；
- `tools/说明.md`：脚本总数与各目录数、每张分类表的条数与表里列出的脚本名、
  「必过 N 项 / 全量 N 项」与 `全量核对.py` 的 `REQUIRED` / `SLOW`。
- 所有文档：同一份里同一个标题不许出现两次（写两遍就会出现「哪份才是新的」这种翻页）。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查文档计数.py

**退出码：0 = 一致，1 = 有漂移**（报出「文档写什么、实际是多少」）。
"""

from __future__ import annotations

import json
import os
import pathlib
import ast
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.cmd.command import registered_command_routes, registered_guard_rules  # noqa: E402
from game.core.combat import expand_build_section  # noqa: E402
from game.core.data import JsonDataService  # noqa: E402

README = ROOT / "README.md"
TOOLS_DOC = ROOT / "tools" / "说明.md"
#: 工具索引里按目录给出的类别；位置列写这些字样的行，数目直接与目录里的脚本数比。
DIRECTORY_CATEGORIES = {
    "架构审查/": "tools/架构审查",
    "行为验证/": "tools/行为验证",
    "报告与生成/": "tools/报告与生成",
    "库/": "tools/库",
    "语料验收/": "tools/验收",
    "公式预览/": "tools/公式预览",
}
SKIP_PARTS = {"__pycache__"}


def _scripts(relative: str) -> list[str]:
    folder = ROOT / relative
    if not folder.is_dir():
        return []
    return sorted(
        path.name
        for path in folder.glob("*.py")
        if path.name != "__init__.py" and not SKIP_PARTS & set(path.parts)
    )


def _directories(relative: str) -> list[str]:
    folder = ROOT / relative
    return sorted(
        path.name
        for path in folder.iterdir()
        if path.is_dir() and not path.name.startswith(("_", ".")) and path.name != "__pycache__"
    )


def _leaf_directories(relative: str) -> list[str]:
    """叶子目录：再往下没有子目录的目录。命令组件按这个数（洞天类可再分组）。"""

    folder = ROOT / relative
    result: list[str] = []
    for path in folder.rglob("*"):
        if not path.is_dir() or path.name == "__pycache__":
            continue
        children = [sub for sub in path.iterdir() if sub.is_dir() and sub.name != "__pycache__"]
        if children:
            continue
        result.append(path.name)
    return sorted(result)


def check_readme_structure() -> list[str]:
    """README 的结构性计数：微服务数、命令组件数、大类与组件数。"""

    text = README.read_text(encoding="utf-8")
    problems: list[str] = []
    core = len(_directories("game/core"))
    features = len(_directories("game/features"))
    command_groups = {
        name: len(_leaf_directories(f"game/cmd/{name}"))
        for name in ("通用", "专属", "特殊地点", "后台")
    }
    categories = len(_directories("data"))
    rules = json.loads((ROOT / "data" / "基础" / "读取规则.json").read_text(encoding="utf-8"))
    components = len(rules["扫描目录"])

    expected = [
        (r"(\d+) 个跨玩法公共微服务", core, "跨玩法公共微服务"),
        (r"(\d+) 个具体玩法微服务", features, "具体玩法微服务"),
        (r"(\d+) 大类、(\d+) 个组件包", None, "大类与组件包"),
    ]
    for pattern, want, label in expected:
        match = re.search(pattern, text)
        if match is None:
            problems.append(f"README 里找不到「{label}」的计数句")
            continue
        if label == "大类与组件包":
            got = (int(match.group(1)), int(match.group(2)))
            want = (categories, components)
            if got != want:
                problems.append(f"README 写「{got[0]} 大类、{got[1]} 个组件包」，实际 {want[0]} / {want[1]}")
        elif int(match.group(1)) != want:
            problems.append(f"README 写「{match.group(1)} 个{label}」，实际 {want}")

    match = re.search(
        r"(\d+) 个二级命令组件（通用 (\d+)、专属 (\d+)、特殊地点 (\d+)、后台 (\d+)）",
        text,
    )
    if match is None:
        problems.append("README 里找不到二级命令组件的计数句")
    else:
        got = tuple(int(value) for value in match.groups())
        want = (
            sum(command_groups.values()),
            command_groups["通用"],
            command_groups["专属"],
            command_groups["特殊地点"],
            command_groups["后台"],
        )
        if got != want:
            problems.append(
                f"README 写「{got[0]} 个二级命令组件（通用 {got[1]}、专属 {got[2]}、特殊地点 {got[3]}、后台 {got[4]}）」，实际 {want}"
            )
    return problems


def check_readme_runtime() -> list[str]:
    """README 的实测规模：JSON 文档/实体/资源池与注册命令、守卫。"""

    text = README.read_text(encoding="utf-8")
    problems: list[str] = []
    status = JsonDataService(ROOT / "data").initialize(expand=expand_build_section)
    match = re.search(r"(\d+) 文档、(\d+) 实体、(\d+) 资源池", text)
    if match is None:
        problems.append("README 里找不到实测规模的计数句")
    else:
        got = tuple(int(value) for value in match.groups())
        want = (status.document_count, status.entity_count, status.pool_count)
        if got != want:
            problems.append(f"README 写「{got[0]} 文档、{got[1]} 实体、{got[2]} 资源池」，实际 {want}")
    match = re.search(r"(\d+) 条命令、(\d+) 条守卫规则", text)
    if match is None:
        problems.append("README 里找不到命令与守卫的计数句")
    else:
        got = (int(match.group(1)), int(match.group(2)))
        want = (len(registered_command_routes()), len(registered_guard_rules()))
        if got != want:
            problems.append(f"README 写「{got[0]} 条命令、{got[1]} 条守卫规则」，实际 {want}")
    return problems


def _category_rows(text: str) -> list[tuple[str, int, str]]:
    """抽出工具索引里的分类表行：类别 / 数量 / 位置。"""

    rows = []
    for line in text.splitlines():
        match = re.fullmatch(r"\| ([^|]+?) \| (\d+) \| [^|]*\| ([^|]+?) \|", line.strip())
        if match is None:
            continue
        rows.append((match.group(1).strip(), int(match.group(2)), match.group(3).strip().strip("`")))
    return rows


def check_tools_totals() -> list[str]:
    """工具索引的总数与各目录数。"""

    text = TOOLS_DOC.read_text(encoding="utf-8")
    problems: list[str] = []
    head = re.search(r"共 \*\*(\d+) 支脚本\*\*：([^（\n]+)", text)
    if head is None:
        return ["工具索引里找不到脚本总数的句子"]
    total = int(head.group(1))
    tail = head.group(2)
    root = re.search(r"根下\s*(\d+)", tail)
    written = {label: int(count) for label, count in re.findall(r"`([^`]+/)`\s*(\d+)", tail)}
    # 目录分类由 DIRECTORY_CATEGORIES 给出：加一个新目录，索引与这里一起加，判据自动跟上。
    want_dirs = {label: len(_scripts(where)) for label, where in DIRECTORY_CATEGORIES.items()}
    want_root = len(_scripts("tools"))
    want_total = want_root + sum(want_dirs.values())
    if root is None or int(root.group(1)) != want_root:
        problems.append(f"工具索引写「根下 {root.group(1) if root else '?'}」，实际 {want_root}")
    if total != want_total:
        problems.append(f"工具索引写「脚本总数 {total}」，实际 {want_total}")
    for label, want in want_dirs.items():
        got = written.get(label)
        if got != want:
            problems.append(f"工具索引写「{label} {got if got is not None else '缺'}」，实际 {want}")

    rows = _category_rows(text)
    if not rows:
        problems.append("工具索引里没有分类表")
        return problems
    for label, count, where in rows:
        if where in DIRECTORY_CATEGORIES:
            actual = len(_scripts(DIRECTORY_CATEGORIES[where]))
            if count != actual:
                problems.append(f"工具索引分类「{label}」写 {count}，{where} 实际 {actual}")
    root_rows = [row for row in rows if row[2] == "根下"]
    root_total = sum(row[1] for row in root_rows)
    if root_total != len(_scripts("tools")):
        problems.append(f"工具索引根下分类合计 {root_total}，根下实际 {len(_scripts('tools'))}")
    return problems


def check_tools_listing() -> list[str]:
    """每一支脚本都要有一处点名；点到的脚本也必须真的还在。

    `架构审查/` 的清单住在它自己的 `说明.md`（那张「各支脚本各管什么」表），
    根下的清单住在本索引；两个方向都查，删了脚本不删清单同样会红。
    """

    problems: list[str] = []
    index = TOOLS_DOC.read_text(encoding="utf-8")
    review_doc = (ROOT / "tools" / "架构审查" / "说明.md").read_text(encoding="utf-8")
    listing = {"tools/架构审查": review_doc}
    for relative in ("tools", *DIRECTORY_CATEGORIES.values()):
        if relative != "tools/架构审查":
            listing[relative] = index
    for relative, text in listing.items():
        for name in _scripts(relative):
            if f"`{name}`" not in text:
                problems.append(f"{relative}/说明没有点名 {name}")
    known = _all_file_names()
    for text in (index, review_doc):
        for name in set(re.findall(r"`([^`/<>*]+\.py)`", text)):
            if name not in known:
                problems.append(f"文档点了不存在的脚本：{name}")
    return problems


#: 全树遍历时要先剪掉的目录：索引与扫描都不该进这里。
_WALK_SKIP = frozenset({".git", ".venv", "node_modules", "_输出", "BUILD", "__pycache__", ".history"})


def _all_file_names() -> set[str]:
    """全仓文件名索引（只建一次）。

    以前这里是对**每个**文档点到的脚本名各调一次 `ROOT.rglob(name)`：
    一次全树遍历几十毫秒，几十个名字叠起来就是一分多钟——文档计数曾是全量里最慢的一支。
    """

    names: set[str] = set()
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [value for value in dirs if value not in _WALK_SKIP]
        names.update(files)
    return names


def _markdown_files() -> list[pathlib.Path]:
    """全仓 markdown（走的时候就剪枝，别等 rglob 走完再筛）。"""

    found: list[pathlib.Path] = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [value for value in dirs if value not in _WALK_SKIP]
        found.extend(pathlib.Path(root) / name for name in files if name.endswith(".md"))
    return sorted(found)


def _check_count(source: str, name: str) -> int:
    """数 `全量核对.py` 里 `REQUIRED` / `SLOW` 各有多少条。"""

    import ast

    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == name:
            return len(node.value.elts)
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == name for target in node.targets
        ):
            return len(node.value.elts)
    raise ValueError(f"全量核对里找不到 {name}")


def check_full_check_counts() -> list[str]:
    """**当前状态**文档里的「必过 N 项」都要与全量核对的条数一致。

    台账（`tools/基准/说明.md`）与各类审查记录是**史册**：里面的旧数字是当时的史实，不管。
    这里只管会随判据增减而必须同步的两处——README 与工具索引。

    真出过事：旧基线页的小标题「36 项必过项里」在加成 37 项之后没人改，
    因为原先只覆盖了工具索引一处，而且那处的标签还错写着 README。后来那一版基线页
    在瘦身里挪出了仓库（正文进 git 历史），所以这里不再把它当「当前状态文档」。
    """

    source = (ROOT / "tools" / "全量核对.py").read_text(encoding="utf-8")
    required = _check_count(source, "REQUIRED")
    problems: list[str] = []
    for doc, pattern, label in (
        (TOOLS_DOC, r"当前必过 (\d+) 项", "工具索引"),
        (ROOT / "README.md", r"必过 (\d+) 项", "README"),
    ):
        match = re.search(pattern, doc.read_text(encoding="utf-8"))
        if match is None:
            problems.append(f"{label}里找不到必过项计数句")
            continue
        if int(match.group(1)) != required:
            problems.append(f"{label}写「{match.group(1)} 项」，实际 {required} 项")
    return problems


#: 展示页目录名 → README 里写的展示名。加一个页面，这里与 README 一起加。
APP_NAMES = {
    "butian": "补天",
    "lianzhen": "演阵台",
    "wanzhen": "万珍殿",
    "lingbao": "灵宝谱",
    "lingtian": "灵田",
    "guiyuan": "归元观",
    "tongquetai": "铜雀台",
    "jiaoyi": "货架",
    "baike": "百科",
    "game-console": "控制台",
    "battle-report": "战报",
    "world-map": "全境舆图",
    "zhuangpei": "装配台",
    "yijing": "意境",
}


def check_readme_files() -> list[str]:
    """README 里的文件与展示页计数：JSON 份数、组件清单份数、展示页面清单。

    这三处当时都漏网过：README 写「1783 份 JSON、29 份组件清单」而实际是 1787 / 30，
    写「四个展示页面：控制台、战报、全境舆图、装配台」——**百科整个没写进去**。
    数得出来的东西就该由判据数，别等人偶然翻到。
    """

    text = README.read_text(encoding="utf-8")
    problems: list[str] = []
    jsons = list((ROOT / "data").rglob("*.json"))
    manifests = list((ROOT / "data").rglob("组件.json"))
    match = re.search(r"(\d+) 份 JSON[^0-9]*?(\d+) 份组件清单", text)
    if match is None:
        problems.append("README 里找不到 JSON 与组件清单的计数句")
    else:
        got = (int(match.group(1)), int(match.group(2)))
        want = (len(jsons), len(manifests))
        if got != want:
            problems.append(f"README 写「{got[0]} 份 JSON、{got[1]} 份组件清单」，实际 {want}")

    apps = [name for name in _directories("static") if name in APP_NAMES]
    match = re.search(r"(\d+) 个展示页面：([^\n]+)", text)
    if match is None:
        problems.append("README 里找不到展示页面的计数句")
    else:
        line = match.group(2)
        if int(match.group(1)) != len(apps):
            problems.append(f"README 写「{match.group(1)} 个展示页面」，实际 {len(apps)}")
        missing = [APP_NAMES[name] for name in apps if APP_NAMES[name] not in line]
        if missing:
            problems.append("README 的展示页面清单漏了：" + "、".join(missing))
    return problems


#: 扫文档时跳过的目录。
DOC_SKIP_PARTS = {"__pycache__", ".venv", ".git", "node_modules", "_输出", "BUILD"}


def check_no_duplicate_sections() -> list[str]:
    """同一份文档里同一个标题不许出现两次。

    出现过真事：message/消息协议说明.md 整篇写了两遍（261 行里 107 行逐字重复），
    读的人得在两份之间判断哪份是新的，改的人也容易改到旧的那一份。
    """

    problems: list[str] = []
    for path in _markdown_files():
        headings = [
            line.strip()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("#")
        ]
        for heading in dict.fromkeys(headings):
            count = headings.count(heading)
            if count > 1:
                problems.append(
                    path.relative_to(ROOT).as_posix()
                    + "：" + heading[:40] + " 出现了 " + str(count) + " 次"
                )
    return problems


LEDGER = ROOT / "tools" / "基准" / "说明.md"


def check_ledger_index() -> list[str]:
    """台账三千多行、30 多个大节，靠「## 目录」那一节导航：每个大节都要在目录里。

    真出过事：这份史册长到没人能翻，加完目录又没人保证以后加节时补行——
    所以让判据点数，而不是靠自觉。
    """

    text = LEDGER.read_text(encoding="utf-8")
    start = text.find("\n## 目录")
    if start < 0:
        return ["台账里找不到「## 目录」那一节"]
    rest = text[start:]
    nxt = rest.find("\n## ", 1)
    if nxt < 0:
        nxt = len(rest)
    toc, body = rest[:nxt], rest[nxt:]
    problems: list[str] = []
    for line in body.split("\n"):
        if not line.startswith("## "):
            continue
        title = line[3:].strip()
        if title == "目录":
            continue
        if ("- " + title) not in toc:
            problems.append(f"台账大节「{title[:24]}」不在目录里")
    return problems


PROTOCOL_DOC = ROOT / "message" / "消息协议说明.md"
BUILDER = ROOT / "message" / "builder.py"


def check_protocol_doc_covers_builder() -> list[str]:
    """协议文档是契约：`DocumentBuilder` 的每个公开方法都得在文档里有名字。

    真出过事：`actions(...)`（底部按钮组的批量写法）一直没写进文档表——
    它是 `action` 的批量版，业务侧要用却查不到。
    """

    tree = ast.parse(BUILDER.read_text(encoding="utf-8"))
    methods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "DocumentBuilder":
            methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
    doc = PROTOCOL_DOC.read_text(encoding="utf-8")
    return [f"协议文档里没写 `{m}` 的用法" for m in methods if (m + "(") not in doc]


ARCHITECTURE_DOC = ROOT / "系统架构.md"
CORE_DOC = ROOT / "核心设定.md"


def _service_counts() -> tuple[int, int]:
    """组合根里的两个服务清单长度——文档写服务数时以它为准。"""

    tree = ast.parse((ROOT / "game" / "app.py").read_text(encoding="utf-8"))
    sizes: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in ("CoreServices", "FeatureServices"):
            sizes[node.name] = sum(1 for child in node.body if isinstance(child, ast.AnnAssign))
    return sizes["CoreServices"], sizes["FeatureServices"]


def _command_component_count() -> int:
    return sum(
        len(_leaf_directories(f"game/cmd/{scope}"))
        for scope in ("通用", "专属", "特殊地点", "后台")
    )


def check_architecture_doc_counts() -> list[str]:
    """`系统架构.md` 的服务数、命令组件数与实测一致。

    真出过事：这一节一直写「45 个玩法微服务、44 个二级命令组件」，而组合根里是
    47 与 46 —— 判据只覆盖了 README，这份权威架构文档反而没人数。
    """

    text = ARCHITECTURE_DOC.read_text(encoding="utf-8")
    core, features = _service_counts()
    commands = _command_component_count()
    problems: list[str] = []
    match = re.search(
        r"当前共有 (\d+) 个核心微服务与 (\d+) 个玩法微服务[^\n]*?(\d+) 个二级命令组件", text
    )
    if match is None:
        problems.append("系统架构.md 里找不到服务与命令组件的计数句")
    else:
        got = tuple(int(value) for value in match.groups())
        want = (core, features, commands)
        if got != want:
            problems.append(
                f"系统架构.md 写「{got[0]} 核心 / {got[1]} 玩法 / {got[2]} 命令组件」，"
                f"实际 {want[0]} / {want[1]} / {want[2]}"
            )
    for pattern, value, label in (
        (r"FeatureServices\s+(\d+) 个玩法微服务", features, "组合根示意图"),
        (r"再创建 (\d+) 个 `FeatureServices`", features, "装配步骤"),
    ):
        found = re.search(pattern, text)
        if found is None:
            problems.append(f"系统架构.md 的{label}里找不到玩法微服务计数")
        elif int(found.group(1)) != value:
            problems.append(f"系统架构.md 的{label}写 {found.group(1)}，实际 {value}")
    return problems


def check_location_count() -> list[str]:
    """地点总数：世界内容里「带坐标的 JSON」条数，文档必须与它一致。

    真出过事：地点从 81 加到 82 之后，五份文档（含 `核心设定.md`）留在 81。
    """

    world = ROOT / "data" / "世界" / "内容"
    actual = 0
    for path in world.rglob("*.json"):
        if path.name == "组件.json":
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and ("坐标" in value or "xy" in value):
            actual += 1
    problems: list[str] = []
    for doc in (CORE_DOC, world / "说明.md", ROOT / "data" / "基础" / "内容" / "说明.md"):
        text = doc.read_text(encoding="utf-8")
        for match in re.finditer(r"(\d+)\s*个(?:正式)?地点", text):
            if int(match.group(1)) != actual:
                problems.append(
                    f"{doc.relative_to(ROOT).as_posix()} 写「{match.group(1)} 个地点」，实际 {actual}"
                )
    return problems


CHECKS = (
    ("README 结构计数", check_readme_structure),
    ("README 实测规模", check_readme_runtime),
    ("README 文件与页面", check_readme_files),
    ("工具索引总数", check_tools_totals),
    ("工具索引点名", check_tools_listing),
    ("核对项数", check_full_check_counts),
    ("架构文档计数", check_architecture_doc_counts),
    ("地点总数", check_location_count),
    ("无重复章节", check_no_duplicate_sections),
    ("台账目录", check_ledger_index),
    ("协议文档覆盖面", check_protocol_doc_covers_builder),
)


def main() -> int:
    problems: list[str] = []
    for name, check in CHECKS:
        try:
            found = check()
        except Exception as exc:  # noqa: BLE001
            found = [f"{type(exc).__name__}: {exc}"]
        for problem in found:
            print(f"  [{name}] {problem}")
        problems.extend(found)
    if problems:
        print(f"文档计数漂移 {len(problems)} 处")
        return 1
    print(f"文档计数审查通过：{len(CHECKS)} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
