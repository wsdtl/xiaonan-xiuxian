"""命名审查：不许拿内置名当自己的名字。

委托方 2026-10：「命名风格统一」。这条最容易落成尺子、也最容易吵起来——
本项目**故意混用中文与 ASCII 标识符**（工具侧用中文、游戏侧用英文），所以「统一到一种风格」本身是错的要求。
真正能机检、又真有害的是另一件事：**遮蔽内置名**——模块级函数/类、以及形参，
用了 `id`／`type`／`list`／`format` 这类内置名，读的人会以为是内置的那个。

**实测（2026-10-12）**：模块级遮蔽 **0 处**；形参遮蔽 **1 处**，
`game/cmd/通用/查看/site.py:34` 的 `baike_data(id)`——那是 **FastAPI 路由的查询参数名**，
改名等于改 URL，属**故意**，进白名单（按「文件::函数::形参」记）。

**顺带记一条被否掉的启发式** ✗：我原本还想查「模块级全小写赋值＝漏了大写」，
全库跑出 **505 处**，全是 `__all__` 与 `router`／`help_registry` 这类**单例**——那是正常写法，
**判据没有意义，弃用**。（常量本身另有实测：全大写的模块级名没有一处写错。）

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查命名.py

**退出码：0 = 干净，1 = 有遮蔽。**
"""
from __future__ import annotations

import ast
import builtins
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
SKIP_PARTS = {".venv", ".git", "__pycache__", "_输出", "BUILD"}
BUILTINS = frozenset(dir(builtins))

#: 已知的故意遮蔽：FastAPI 路由的查询参数名就是 API 的一部分，改名等于改 URL。
KNOWN = frozenset({
    "game/cmd/通用/查看/site.py::baike_data::id",
})


def main() -> int:
    problems: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        if SKIP_PARTS & set(path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in BUILTINS:
                    problems.append(f"{rel}:{node.lineno} 模块级 {node.name} 遮蔽内置名")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for arg in [*node.args.args, *node.args.kwonlyargs, *node.args.posonlyargs]:
                    if arg.arg not in BUILTINS:
                        continue
                    if f"{rel}::{node.name}::{arg.arg}" in KNOWN:
                        continue
                    problems.append(f"{rel}:{node.lineno} {node.name}({arg.arg}) 形参遮蔽内置名")
    if problems:
        for item in problems:
            print(f"   {item}")
        print(f"命名审查 {len(problems)} 处")
        return 1
    print("命名审查通过：没有遮蔽内置名")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
