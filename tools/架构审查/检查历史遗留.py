"""历史遗留守门：已清掉的东西不许回来。

四组检查：

1. **归档目录与命名不得回来**：`tools/` 下的目录名与文件名都不带一次性 / 迁移 / 原型 / 归档 / 废弃；
2. **悬空脚本引用**：文档里以反引号点名的 `*.py` 必须真实存在（删脚本不删文档同样要红）；
3. **脚本都得有执行者**：`tools/` 下的脚本要么被别的文件点名，要么被 import——
   只写不用的脚本和删一半的重构一样是旧账；
5. **自映射别名表**：`game/` 里整表都是 `{"A": "A"}` 的字典等于默认分支，属空转兼容层。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查历史遗留.py

**退出码：0 = 干净，1 = 有历史遗留。**
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TOOLS = ROOT / "tools"
GAME = ROOT / "game"
#: 已经清掉的目录：名字里带这些词的一律不许再出现在 tools/ 下。
FORBIDDEN_DIR_WORDS = ("一次性", "迁移", "原型", "归档", "废弃")
#: 文档里点名脚本的形态：反引号包起来的 xxx.py（可带目录前缀）。
SCRIPT_REF = re.compile(r"`([^`\s]*?([A-Za-z0-9_\u4e00-\u9fff-]+)\.py)`")
#: import 行：判断脚本有没有调用者时只看这些行，不看全文。
IMPORT_LINE = re.compile(r"\s*(?:from|import)\s")
#: 已弃用或已移除的标准库 API：出现即红（3.12 起弃用的那批 + 更早移除的）。
DEPRECATED_APIS = (
    "asyncio.set_event_loop_policy",
    "asyncio.get_event_loop_policy",
    "WindowsSelectorEventLoopPolicy",
    "WindowsProactorEventLoopPolicy",
    "asyncio.get_event_loop(",
    "asyncio.coroutine",
    "asyncio.Task.all_tasks",
    "datetime.utcnow",
    "datetime.utcfromtimestamp",
    "ssl.match_hostname",
    "locale.getdefaultlocale",
    "pkg_resources",
    "distutils",
)


def check_archive_dirs() -> list[str]:
    """tools/ 下不得再有一次性 / 迁移 / 原型 目录。"""

    problems: list[str] = []
    for entry in sorted(TOOLS.iterdir()):
        if not entry.is_dir():
            continue
        if any(word in entry.name for word in FORBIDDEN_DIR_WORDS):
            problems.append(f"tools/{entry.name}/ 是已清掉的归档目录")
    return problems


def check_dangling_script_refs() -> list[str]:
    """文档点名的脚本必须存在。"""

    problems: list[str] = []
    names = {p.name for p in ROOT.rglob("*.py")}
    for path in sorted(ROOT.rglob("*.md")):
        if {".venv", ".git", "_输出"} & set(path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for full, base in SCRIPT_REF.findall(line):
                if any(ch in full for ch in "<>*"):
                    continue
                if f"{base}.py" not in names:
                    problems.append(
                        f"{path.relative_to(ROOT).as_posix()}:{line_no} 点了不存在的脚本 {full}"
                    )
    return problems


def check_forbidden_tool_names() -> list[str]:
    """tools/ 下的**目录名与文件名**都不许带一次性 / 迁移 / 原型 / 归档 / 废弃。

    只查目录名会漏掉 `构筑模板迁移.py` 这种漏网的一次性脚本。`基准/` 例外：它是
    产物目录，复算用的旧摘要按定义就住在这里。
    """

    problems: list[str] = []
    for path in sorted(TOOLS.rglob("*")):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(TOOLS)
        if relative.parts and relative.parts[0] == "基准":
            continue
        hit = next((word for word in FORBIDDEN_DIR_WORDS if word in path.stem), "")
        if hit:
            kind = "目录" if path.is_dir() else "脚本"
            problems.append(
                f"{path.relative_to(ROOT).as_posix()} 是已清掉的{kind}（名字带「{hit}」）"
            )
    return problems


def check_scripts_have_callers() -> list[str]:
    """tools/ 下的脚本都得有人叫得动：被别的文件点名，或被 import。

    包内的 __init__.py 不算——它由导入机制装载，不需要调用者。
    先把全文与导入行各聚一次，再逐脚本比对：逐文件正则会把这项从 11 秒拖到 29 秒。
    """

    blob: list[str] = []
    imports: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".md"}:
            continue
        if {".venv", ".git", "_输出", "__pycache__"} & set(path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        blob.append(text)
        imports.extend(
            line for line in text.splitlines() if IMPORT_LINE.match(line)
        )
    haystack = "\n".join(blob)
    problems: list[str] = []
    for script in sorted(TOOLS.rglob("*.py")):
        if script.name == "__init__.py":
            continue
        stem = script.stem
        dotted = script.relative_to(ROOT).with_suffix("").as_posix().replace("/", ".")
        if f"{stem}.py" in haystack or dotted in haystack:
            continue
        if any(stem in line for line in imports):
            continue
        problems.append(
            f"{script.relative_to(ROOT).as_posix()} 没有任何执行者（既没被点名也没被导入）"
        )
    return problems


def check_unused_imports() -> list[str]:
    """导入了却没用，就是没清干净的残渣。

    __init__.py 不算：那里的导入是**故意转出**的公开 API，本就不该在本文件里使用。
    冻结层（launch/ 与 message/）当前也是 0 处，所以一并纳入检查。
    """

    problems: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if {".venv", ".git", "_输出", "__pycache__"} & set(path.parts):
            continue
        if path.name == "__init__.py":
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        imported: dict[str, int] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported[alias.asname or alias.name.split(".")[0]] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name != "*":
                        imported[alias.asname or alias.name] = node.lineno
        used: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                current: ast.expr = node
                while isinstance(current, ast.Attribute):
                    current = current.value
                if isinstance(current, ast.Name):
                    used.add(current.id)
        body = "\n".join(
            line
            for line in source.splitlines()
            if not line.strip().startswith(("import ", "from "))
        )
        for name, line in imported.items():
            if name == "annotations" or name in used or name in body:
                continue
            problems.append(
                f"{path.relative_to(ROOT).as_posix()}:{line} 导入了 {name} 却没用"
            )
    return problems


def check_deprecated_apis() -> list[str]:
    """弃用的标准库 API 不许进来。

    `main.py` 原先调 `asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())`：
    它从第一个提交起就是没有依据的样板（全库没有一处用 Selector 循环独有的
    `add_reader`），而这两个 API 都已弃用。删掉之后由这条守着，别再写回去。

    本文件要写下这些 API 的名字才查得了它们，所以豁免自身；注释行不算调用。
    """

    problems: list[str] = []
    guard = pathlib.Path(__file__).resolve()
    for path in sorted(ROOT.rglob("*.py")):
        if {".venv", ".git", "_输出", "__pycache__"} & set(path.parts):
            continue
        if path.resolve() == guard:
            continue
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.lstrip().startswith("#"):
                continue
            for api in DEPRECATED_APIS:
                if api in line:
                    problems.append(
                        f"{path.relative_to(ROOT).as_posix()}:{line_no} 用了已弃用的 {api}"
                    )
    return problems


def check_self_mapping_tables() -> list[str]:
    """整表 {"A": "A"} 的字典就是空转，等价于 get(key, key)。"""

    problems: list[str] = []
    for path in sorted(GAME.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict) or len(node.keys) < 2:
                continue
            pairs: list[tuple[str, str]] = []
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(value, ast.Constant):
                    pairs.append((str(key.value), str(value.value)))
                else:
                    pairs.append(("", ""))
            if pairs and all(a and a == b for a, b in pairs):
                problems.append(
                    f"{path.relative_to(ROOT).as_posix()}:{node.lineno} "
                    f"自映射别名表（{len(pairs)} 项全部键值相同）"
                )
    return problems


CHECKS = (
    ("归档目录", check_archive_dirs),
    ("禁用命名", check_forbidden_tool_names),
    ("悬空脚本引用", check_dangling_script_refs),
    ("脚本执行者", check_scripts_have_callers),
    ("自映射别名表", check_self_mapping_tables),
    ("弃用 API", check_deprecated_apis),
    ("未使用的导入", check_unused_imports),
)


def main() -> int:
    problems: list[str] = []
    for name, check in CHECKS:
        found = check()
        print(f"  [{name}] {'干净' if not found else str(len(found)) + ' 处'}")
        for item in found[:20]:
            print(f"    {item}")
        problems.extend(found)
    if problems:
        print(f"历史遗留 {len(problems)} 处")
        return 1
    print(f"历史遗留守门通过：{len(CHECKS)} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
