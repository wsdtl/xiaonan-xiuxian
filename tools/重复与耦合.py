"""重复与耦合测量：`game/` 里哪些代码是抄出来的、哪些包依赖最多。

「简化代码、减少耦合」最容易变成凭感觉乱动，所以先量。三样：

  1. 重复**函数体**——AST 归一化（抹掉函数名、参数名、文档字符串、字面量）后相同的
     函数分组，按「能省下多少行」排序；
  2. 最长函数——简化通常藏在这里；
  3. 耦合——被最多文件导入的模块、各包扇出。

    .venv/Scripts/python.exe -X utf8 tools/重复与耦合.py
    # 报告写到 _重复与耦合.txt（根目录 _* 不入库）

**读数的坑**：归一化抹掉了异常类型与字面量，所以「结构相同」不等于「可以合并」。
例：60 处 `_positive_int` 看着逐字相同，实际分别抛 `JsonDataError`、`AssetStateError`
等**各服务自己的错误类型**——那是有意设计（命令层捕获的就是各服务的错误）。
第一段给的是**去重上限**，不是能直接删掉的量；动手前必须逐组看清差异。

**已知的负结果**（量过、不用再查）：`game.app` 被 41 个文件导入，但**全在 `game/cmd`**
（38 个 `__init__.py` + `access_guard`/`site`/`runtime`），`features` 与 `core` 一处都
没有——那是规范要的形态（回调从组合根取服务），不是耦合。
"""

from __future__ import annotations

import ast
import collections
import io
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
GAME = ROOT / "game"
out = io.TextIOWrapper(open(ROOT / "_重复与耦合.txt", "wb"), encoding="utf-8")


def normalize(node: ast.AST) -> str:
    """归一化：丢弃标识符与字面量的具体值，只留结构。"""

    class Normalizer(ast.NodeTransformer):
        def visit_Name(self, item: ast.Name) -> ast.AST:
            return ast.copy_location(ast.Name(id="_", ctx=item.ctx), item)

        def visit_arg(self, item: ast.arg) -> ast.AST:
            item.arg = "_"
            item.annotation = None
            return item

        def visit_Constant(self, item: ast.Constant) -> ast.AST:
            return ast.copy_location(ast.Constant(value=type(item.value).__name__), item)

        def visit_FunctionDef(self, item: ast.FunctionDef) -> ast.AST:
            item.name = "_"
            item.decorator_list = []
            item.returns = None
            return self.generic_visit(item)

        def visit_AsyncFunctionDef(self, item: ast.AsyncFunctionDef) -> ast.AST:
            item.name = "_"
            item.decorator_list = []
            item.returns = None
            return self.generic_visit(item)

    copied = ast.parse(ast.unparse(node))
    return ast.dump(Normalizer().visit(copied))


def collect():
    functions: list[tuple[str, str, int, int]] = []
    bodies: dict[tuple[str, str, int], ast.AST] = {}
    imports: collections.Counter = collections.Counter()
    package_imports: dict[str, set[str]] = collections.defaultdict(set)
    for path in sorted(GAME.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(ROOT).as_posix()
        package = "/".join(rel.split("/")[:3])
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = [
                    item for item in node.body
                    if not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant))
                ]
                if not body:
                    continue
                end = max(getattr(item, "end_lineno", node.lineno) for item in body)
                functions.append((rel, node.name, node.lineno, end - node.lineno + 1))
                bodies[(rel, node.name, node.lineno)] = node
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for module in modules:
                    if not module.startswith("game."):
                        continue
                    imports[module] += 1
                    target = "/".join(module.split(".")[:3])
                    if target and target != package:
                        package_imports[package].add(target)
    return functions, bodies, imports, package_imports


def main() -> int:
    functions, bodies, imports, package_imports = collect()

    out.write("=" * 96 + "\n")
    out.write("一、重复函数体（归一化后相同，按可省行数排序）\n")
    out.write("=" * 96 + "\n")
    groups: dict[str, list[tuple[str, str, int, int]]] = collections.defaultdict(list)
    for rel, name, line, size in functions:
        node = bodies[(rel, name, line)]
        groups[normalize(node)].append((rel, name, line, size))
    duplicates = sorted(
        (group for group in groups.values() if len(group) > 1),
        key=lambda group: -(len(group) - 1) * group[0][3],
    )
    saved = sum((len(group) - 1) * group[0][3] for group in duplicates)
    out.write(
        f"函数总数 {len(functions)}；重复组 {len(duplicates)} 组；"
        f"涉及函数 {sum(len(group) for group in duplicates)} 个；"
        f"**结构级**去重上限约 {saved} 行\n"
    )
    out.write("注意：归一化抹掉了异常类型与字面量，所以这个数是上限，不是可直接删的量。\n\n")
    for group in duplicates[:20]:
        rel, name, line, size = group[0]
        out.write(f"  {len(group)} 处 × {size} 行 = 省 {(len(group) - 1) * size} 行   [{name}]\n")
        for item in group[:5]:
            out.write(f"        {item[0]}:{item[2]}\n")
        if len(group) > 5:
            out.write(f"        …… 还有 {len(group) - 5} 处\n")

    out.write("\n" + "=" * 96 + "\n")
    out.write("二、最长的 15 个函数（简化通常藏在这里）\n")
    out.write("=" * 96 + "\n")
    for rel, name, line, size in sorted(functions, key=lambda item: -item[3])[:15]:
        out.write(f"  {size:>4} 行  {rel}:{line}  {name}\n")

    out.write("\n" + "=" * 96 + "\n")
    out.write("三、耦合热点：被最多文件导入的 game 模块\n")
    out.write("=" * 96 + "\n")
    for module, count in imports.most_common(15):
        out.write(f"  {count:>4} 次  {module}\n")

    out.write("\n" + "=" * 96 + "\n")
    out.write("四、跨包扇出最多的包（依赖别人最多 = 最该降耦的候选）\n")
    out.write("=" * 96 + "\n")
    for package, targets in sorted(package_imports.items(), key=lambda kv: -len(kv[1]))[:15]:
        out.write(f"  扇出 {len(targets):>3}  {package}\n")

    out.write("\n注：`game.app` 虽然被 41 个文件导入，但全在 `game/cmd`，"
              "`features`/`core` 一处都没有——不是耦合。\n")
    out.flush()
    print(f"详见 _重复与耦合.txt：函数 {len(functions)} 个、重复组 {len(duplicates)} 组")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
