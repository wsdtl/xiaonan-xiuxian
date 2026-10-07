"""历史遗留守门：已清掉的东西不许回来。

三组检查：

1. **归档目录不得回来**：`tools/` 下不再有一次性 / 迁移 / 原型 目录；
2. **悬空脚本引用**：文档里以反引号点名的 `*.py` 必须真实存在（删脚本不删文档同样要红）；
3. **自映射别名表**：`game/` 里整表都是 `{"A": "A"}` 的字典等于默认分支，属空转兼容层。

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
    ("悬空脚本引用", check_dangling_script_refs),
    ("自映射别名表", check_self_mapping_tables),
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
