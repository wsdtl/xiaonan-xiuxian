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

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查文档计数.py

**退出码：0 = 一致，1 = 有漂移**（报出「文档写什么、实际是多少」）。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.cmd.command import registered_command_routes, registered_guard_rules  # noqa: E402
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


def check_readme_structure() -> list[str]:
    """README 的结构性计数：微服务数、命令组件数、大类与组件数。"""

    text = README.read_text(encoding="utf-8")
    problems: list[str] = []
    core = len(_directories("game/core"))
    features = len(_directories("game/features"))
    command_groups = {name: len(_directories(f"game/cmd/{name}")) for name in ("通用", "专属", "后台")}
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

    match = re.search(r"(\d+) 个二级命令组件（通用 (\d+)、专属 (\d+)、后台 (\d+)）", text)
    if match is None:
        problems.append("README 里找不到二级命令组件的计数句")
    else:
        got = tuple(int(value) for value in match.groups())
        want = (sum(command_groups.values()), command_groups["通用"], command_groups["专属"], command_groups["后台"])
        if got != want:
            problems.append(f"README 写「{got[0]} 个二级命令组件（通用 {got[1]}、专属 {got[2]}、后台 {got[3]}）」，实际 {want}")
    return problems


def check_readme_runtime() -> list[str]:
    """README 的实测规模：JSON 文档/实体/资源池与注册命令、守卫。"""

    text = README.read_text(encoding="utf-8")
    problems: list[str] = []
    status = JsonDataService(ROOT / "data").initialize()
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
    for text in (index, review_doc):
        for name in set(re.findall(r"`([^`/<>*]+\.py)`", text)):
            if not any(path.is_file() for path in ROOT.rglob(name)):
                problems.append(f"文档点了不存在的脚本：{name}")
    return problems


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
    """工具索引里的「必过 N 项」与全量核对的实际条数。"""

    source = (ROOT / "tools" / "全量核对.py").read_text(encoding="utf-8")
    required = _check_count(source, "REQUIRED")
    text = TOOLS_DOC.read_text(encoding="utf-8")
    problems: list[str] = []
    for pattern, want, label in (
        (r"当前必过 (\d+) 项", (required,), "必过"),
    ):
        match = re.search(pattern, text)
        if match is None:
            problems.append(f"工具索引里找不到「{label}」的计数句")
            continue
        got = tuple(int(value) for value in match.groups())
        if got != want:
            problems.append(f"工具索引写「{'、'.join(str(v) for v in got)}」（{label}），实际 {want}")
    return problems


CHECKS = (
    ("README 结构计数", check_readme_structure),
    ("README 实测规模", check_readme_runtime),
    ("工具索引总数", check_tools_totals),
    ("工具索引点名", check_tools_listing),
    ("核对项数", check_full_check_counts),
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
