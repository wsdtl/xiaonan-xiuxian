"""重复定义审查：同一处不许重复定义同名函数，同一作用域不许重复 import。

委托方 2026-10：「整理代码…复制粘贴出来的重复逻辑」。这两条是重复里**最没有争议**的两种，
都能机械地判死：

1. **同一个作用域里重复定义同名函数**：后一个会**静默遮蔽**前一个，前一个彻底死掉。
   真出过事：`tests/test_alchemy_missing_guidance.py` 里 `_本脉灵植` 被定义了两遍，两份体一字不差。
2. **同一个作用域里重复 import 同一件事**：不报错、不生效差别，纯粹是复制粘贴的残渣。
   真出过事：两个测试文件在模块级把 `json`／`Path`／`pytest`／`asyncio`／`FastAPI` 各 import 两三遍。

**只看作用域的直接子句**（不钻进 `if`/`try` 里面）：条件式 import 与分支里的同名函数是合法写法，
本判据不管它们，免得误报。

**跨文件的「同体函数」不做判据**：全库 11 组（`_plain`×4、`_speech`×3、`_short_id`×3…），
多数是「各服务各留一份小助手」的有意设计，判死会误伤；那属于**人工判断**，不属于尺子。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查重复定义.py

**退出码：0 = 干净，1 = 有重复。**
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SKIP_PARTS = {".venv", ".git", "__pycache__", "_输出", "BUILD"}


def _scopes(tree: ast.Module) -> list[tuple[str, list[ast.stmt]]]:
    """模块、类、函数的「直接子句」清单。"""

    out: list[tuple[str, list[ast.stmt]]] = [("模块", list(tree.body))]
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, list(node.body)))
    return out


def _import_key(node: ast.stmt) -> str:
    """一次 import 的规范化字样——按**绑定名**算，不按模块名。

    这正是本判据第一版的 bug：`import pathlib as _pathlib` 与 `import pathlib` 被当成同一个键，
    于是把「打补丁 sys.path 之前先拿住标准库」的那个 `_pathlib` 判成重复，一删就全线 NameError。
    **绑定名不同就是两件事。**
    """

    if isinstance(node, ast.Import):
        names = sorted(a.asname or a.name.split(".")[0] for a in node.names)
        return "import " + ", ".join(names)
    assert isinstance(node, ast.ImportFrom)
    names = sorted(a.asname or a.name for a in node.names)
    return "from " + str(node.module) + " import " + ", ".join(names)


def main() -> int:
    problems: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if SKIP_PARTS & set(path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for scope, body in _scopes(tree):
            defined: dict[str, int] = {}
            imported: dict[str, int] = {}
            for stmt in body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if stmt.name in defined:
                        problems.append(
                            f"{rel}:{stmt.lineno} 在「{scope}」里重复定义 {stmt.name}"
                            f"（第一次在第 {defined[stmt.name]} 行）"
                        )
                    else:
                        defined[stmt.name] = stmt.lineno
                elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    key = _import_key(stmt)
                    if key in imported:
                        problems.append(
                            f"{rel}:{stmt.lineno} 在「{scope}」里重复 import：{key}"
                            f"（第一次在第 {imported[key]} 行）"
                        )
                    else:
                        imported[key] = stmt.lineno
    if problems:
        for item in problems:
            print(f"   {item}")
        print(f"重复定义审查 {len(problems)} 处")
        return 1
    print("重复定义审查通过：无重复函数、无重复 import")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
