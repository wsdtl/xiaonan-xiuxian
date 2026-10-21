"""文件结构：`__all__` 必须是模块里最后一条语句。

理由：它是一份"本模块对外卖什么"的清单，位置在**最后**才让人一眼看全；
写在中间时，后面新增的东西就不会出现在清单里（本仓库真栽过：往末尾追加了两个
公共函数，`__all__` 被挤到中间，那份清单当场变成谎话）。

只看**位置**，不看顺序内容：模块级 `__all__` 若是最后一条语句即通过。
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SKIP_DIRS = {"__pycache__", ".venv", ".git", "_输出", "BUILD", "database"}


def _python_files(root: Path):
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = [v for v in subdirs if v not in SKIP_DIRS]
        for name in sorted(names):
            if name.endswith(".py"):
                yield Path(directory) / name


def main() -> int:
    problems: list[str] = []
    for path in _python_files(ROOT):
        relative = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            problems.append(f"{relative}: 读不出语法树（SyntaxError），判据无从判定")
            continue
        body = tree.body
        for index, node in enumerate(body):
            if not isinstance(node, ast.Assign):
                continue
            if not any(getattr(target, "id", "") == "__all__" for target in node.targets):
                continue
            if index != len(body) - 1:
                later = len(body) - 1 - index
                problems.append(f"{relative}:{node.lineno} 的 __all__ 后面还有 {later} 条语句")
    for item in problems:
        print("   [__all__ 不在最后] " + item)
    if problems:
        print("文件结构审查 %d 处有问题" % len(problems))
        return 1
    print("文件结构审查通过：所有 __all__ 都在模块最后一条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
