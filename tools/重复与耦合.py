"""重复与耦合测量：`game/` 里哪些代码是抄出来的、哪些包依赖最多。

「简化代码、减少耦合」最容易变成凭感觉乱动，所以先量。三样：

  1. 重复**函数体**——AST 归一化（抹掉函数名、参数名、文档字符串、字面量）后相同的
     函数分组，按「能省下多少行」排序；
  2. 最长函数——简化通常藏在这里；
  3. 耦合——被最多文件导入的模块、各包扇出。

    .venv/Scripts/python.exe -X utf8 tools/重复与耦合.py
    # 报告写到 _重复与耦合.txt（根目录 _* 不入库）

**读数的坑（两种口径都要看）**：宽松口径把所有标识符与字面量都抹成同形，于是
「结构相同」既不等于「同一个函数」，也不等于「可以合并」——它会把**不同的校验器**
并成一组：`_positive_int`（`value < 1`）、`_nonnegative_int`（`value < 0`）、
`_number`（`float`）、`_bool`，以及 60 处里各服务自己的错误类型，看着全都一样。
照宽松口径去合并就是静默的行为错误。

所以报告给两个数：**严格口径**（只抹异常类名，判定、比较常量与消息一律保留）才是
能动手的量；**宽松口径**只是去重上限。动手前仍要逐组看清差异。

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

#: 算「分支点」时计入的节点：每个都代表一个决策点。
BRANCH_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.ExceptHandler,
                ast.IfExp, ast.BoolOp, ast.comprehension, ast.Match)


def depth_of(node: ast.AST, level: int = 0) -> int:
    """最大嵌套深度：只沿控制流语句往下算，普通表达式不算深。"""

    deepest = level
    for child in ast.iter_child_nodes(node):
        step = level + 1 if isinstance(child, (ast.If, ast.For, ast.AsyncFor,
                                              ast.While, ast.Try, ast.With,
                                              ast.AsyncWith, ast.Match)) else level
        deepest = max(deepest, depth_of(child, step))
    return deepest


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


def normalize_strict(node: ast.AST) -> str:
    """严格归一化：只抹掉异常类名与注解，判定、比较常量、消息文本一律保留。

    这一口径下被判为重复的，差异就只剩「抛哪个异常」——那才是真能合并的组。
    文档字符串在这里去掉：有的副本写了、有的没写，不该因此分成两组。
    """

    class Strict(ast.NodeTransformer):
        def visit_arg(self, item: ast.arg) -> ast.AST:
            item.annotation = None
            return item

        def visit_Raise(self, item: ast.Raise) -> ast.AST:
            if isinstance(item.exc, ast.Call) and isinstance(item.exc.func, ast.Name):
                if item.exc.func.id != "error":  # 已经参数化的副本不必再抹
                    item.exc.func = ast.Name(id="E", ctx=ast.Load())
            return self.generic_visit(item)

        def visit_FunctionDef(self, item: ast.FunctionDef) -> ast.AST:
            item.name = "_"
            item.decorator_list = []
            item.returns = None
            item.body = [
                child for child in item.body
                if not (isinstance(child, ast.Expr)
                        and isinstance(child.value, ast.Constant))
            ]
            return self.generic_visit(item)

        def visit_AsyncFunctionDef(self, item: ast.AsyncFunctionDef) -> ast.AST:
            return self.visit_FunctionDef(item)  # type: ignore[arg-type]

    copied = ast.parse(ast.unparse(node))
    return ast.dump(Strict().visit(copied))


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
    out.write("一、重复函数体（按可省行数排序）\n")
    out.write("=" * 96 + "\n")
    groups: dict[str, list[tuple[str, str, int, int]]] = collections.defaultdict(list)
    loose: dict[str, list[tuple[str, str, int, int]]] = collections.defaultdict(list)
    for rel, name, line, size in functions:
        node = bodies[(rel, name, line)]
        groups[normalize_strict(node)].append((rel, name, line, size))
        loose[normalize(node)].append((rel, name, line, size))
    duplicates = sorted(
        (group for group in groups.values() if len(group) > 1),
        key=lambda group: -(len(group) - 1) * (group[0][3] - 1),
    )
    loose_duplicates = [group for group in loose.values() if len(group) > 1]
    # 每个副本换成一行导入，所以每组省 (副本数-1) × (行数-1)。
    saved = sum((len(group) - 1) * (group[0][3] - 1) for group in duplicates)
    loose_saved = sum((len(group) - 1) * (group[0][3] - 1) for group in loose_duplicates)
    out.write(
        f"函数总数 {len(functions)}；严格口径重复组 {len(duplicates)} 组"
        f"（涉及函数 {sum(len(group) for group in duplicates)} 个）；"
        f"宽松口径 {len(loose_duplicates)} 组。\n"
    )
    out.write(
        f"**能动手的量**：严格口径去重上限约 {saved} 行；"
        f"宽松口径给的 {loose_saved} 行是上限，不可直接照做（见开头两种口径的说明）。\n\n"
    )
    for group in duplicates[:20]:
        rel, name, line, size = group[0]
        out.write(f"  {len(group)} 处 × {size} 行 = 省 {(len(group) - 1) * (size - 1)} 行   [{name}]\n")
        for item in group[:5]:
            out.write(f"        {item[0]}:{item[2]}\n")
        if len(group) > 5:
            out.write(f"        …… 还有 {len(group) - 5} 处\n")

    out.write("\n" + "=" * 96 + "\n")
    out.write("二、≥120 行的函数：行数之外还要看**分支密度**与嵌套深度\n")
    out.write("=" * 96 + "\n")
    out.write("行数本身不是判据。长度有两种，成分完全不同：\n")
    out.write("  线性展开——一长串顺序处理，分支少、嵌套浅。长度来自「事情有几件」而不是\n")
    out.write("    「逻辑有多绕」。典型：组合根（每服务一段构造 + 初始化 + 日志）、\n")
    out.write("    按能力名平铺的 if 链（每个原子能力一条）。拆它只是把同样的展开搬走。\n")
    out.write("  真复杂——分支密集、嵌套深，每个分支是一个决策点。这种才值得拆。\n\n")
    out.write(f"{'行数':>5}{'语句':>6}{'分支':>6}{'深度':>5}{'分支/百行':>10}  函数\n")
    long_functions = []
    for rel, name, line, size in functions:
        if size < 120:
            continue
        node = bodies[(rel, name, line)]
        statements = sum(1 for item in ast.walk(node) if isinstance(item, ast.stmt))
        branches = sum(1 for item in ast.walk(node) if isinstance(item, BRANCH_NODES))
        long_functions.append((size, statements, branches, depth_of(node),
                               branches / size * 100, rel, line, name))
    for size, statements, branches, depth, density, rel, line, name in sorted(
        long_functions, reverse=True
    ):
        out.write(f"{size:>5}{statements:>6}{branches:>6}{depth:>5}{density:>10.1f}"
                  f"  {rel}:{line} {name}\n")
    if long_functions:
        average = sum(item[4] for item in long_functions) / len(long_functions)
        out.write(f"\n  ≥120 行函数 {len(long_functions)} 个，共 "
                  f"{sum(item[0] for item in long_functions)} 行；"
                  f"平均分支密度 {average:.1f}\n")
        out.write("  密度明显**低于**平均的是线性展开（别拆）；明显高于且嵌套深的才值得看。\n")

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
