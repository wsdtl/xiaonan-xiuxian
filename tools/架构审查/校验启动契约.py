"""组合根（`game/app.py`）启动契约审查。

`game/app.py` 是唯一组合根，承担 38 个核心服务与 39 个玩法微服务的装配。
它的装配顺序、初始化播报和接收者配对是跨模块的运行契约，但此前没有任何
检查约束。本脚本把这四条规则固定下来：

1. 每个核心微服务在初始化后播报一条自己的启动事实；
2. 玩法微服务不逐条播报，避免启动输出被命令级日志淹没；
3. `X.initialize()` 的接收者必须是本段刚构造的服务；
4. 每个服务只构造一次，且硬依赖顺序成立。

属于维护审查，不进入游戏启动流程，也不被 `game` 依赖。

用法：

```powershell
.venv/Scripts/python.exe -X utf8 tools/架构审查/校验启动契约.py
```

退出码 0 表示全部通过；1 表示存在违反项。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP = PROJECT_ROOT / "game" / "app.py"

CTOR = re.compile(r"^    (\w+) = (\w+)(Service|Feature)\(")
INIT = re.compile(r"^    (\w+) = (\w+)\.initialize\(\)$")

# 被依赖者必须先构造。顺序错误会让服务拿到半加载状态。
REQUIRED_BEFORE = {
    "combat": "formation",
    "character": "forging",
    "character": "sect_library",
    "sect_facilities": "sect_assets",
    "sect_production": "sect_assets",
    "sect_war": "sect",
    "exploration": "enemy",
    "raid": "enemy",
}
# 需要输出启动结果的玩法微服务；其余玩法不逐条播报。
LOGGING_FEATURES = {"create_character", "ditu"}


def _build_body() -> list[str]:
    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "build_game_services"
        ),
        None,
    )
    if function is None:
        raise SystemExit("game/app.py 中找不到 build_game_services")
    lines = source.splitlines()
    start = function.body[0].lineno - 1
    end = function.end_lineno or start + 1
    return lines[start:end]


def _component_spans() -> list[tuple[str, str, ast.Assign]]:
    """返回每个组件构造的 (变量名, 种类, AST 节点)。

    构造可以是多行调用，因此必须用 AST 的结束行定位其后的 initialize 语句，
    不能假设 initialize 紧跟在开括号那一行之后。
    """

    source = APP.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "build_game_services"
        ),
        None,
    )
    if function is None:
        raise SystemExit("game/app.py 中找不到 build_game_services")
    spans: list[tuple[str, str, ast.Assign]] = []
    for statement in function.body:
        if not isinstance(statement, ast.Assign) or not isinstance(statement.value, ast.Call):
            continue
        call = statement.value
        name = getattr(call.func, "id", "")
        if not name.endswith(("Service", "Feature")):
            continue
        kind = "feature" if name.endswith("Feature") else "core"
        target = statement.targets[0]
        if isinstance(target, ast.Name):
            spans.append((target.id, kind, statement))
    return spans


def _components() -> list[tuple[int, str, str]]:
    found: list[tuple[int, str, str]] = []
    for index, line in enumerate(_build_body()):
        match = CTOR.match(line)
        if match:
            kind = "feature" if match.group(3) == "Feature" else "core"
            found.append((index, match.group(1), kind))
    return found


def _blocks() -> list[tuple[str, str, list[str]]]:
    body = _build_body()
    components = _components()
    result: list[tuple[str, str, list[str]]] = []
    for position, (index, variable, kind) in enumerate(components):
        end = components[position + 1][0] if position + 1 < len(components) else len(body)
        result.append((variable, kind, body[index + 1 : end]))
    return result


def check_logging() -> list[str]:
    problems: list[str] = []
    for variable, kind, block in _blocks():
        logged = any("logger.opt(colors=True).success" in line for line in block)
        if kind == "core" and not logged:
            problems.append(f"核心服务 {variable} 缺少初始化播报")
        if kind == "feature" and logged and variable not in LOGGING_FEATURES:
            problems.append(f"玩法微服务 {variable} 不应逐条播报启动事实")
    return problems


def check_receivers() -> list[str]:
    """只校验捕获返回值的情形：`X = Y.initialize()` 的 X 必须与本段服务 Y 同名。

    玩法服务的 `X.initialize()` 不接收返回值是合法的（返回 None），因此不作为
    越界。曾经的真实缺陷是把状态赋给了别的服务名（`item_status = data.initialize()`），
    本条检查正是为了拦住它。
    """

    problems: list[str] = []
    tree = ast.parse(APP.read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_game_services"
    )
    body_offset = function.body[0].lineno - 1
    body = _build_body()
    for variable, _kind, statement in _component_spans():
        window = body[statement.end_lineno - body_offset : statement.end_lineno - body_offset + 3]
        for line in window:
            if not line.strip():
                continue
            matched = INIT.match(line)
            if matched is not None and matched.group(2) != variable:
                problems.append(
                    f"{variable} 的 initialize 接收者是 {matched.group(2)}，与本段构造不一致"
                )
            break
    return problems


def check_order() -> list[str]:
    problems: list[str] = []
    order = [variable for _index, variable, _kind in _components()]
    duplicates = {name for name in order if order.count(name) > 1}
    if duplicates:
        problems.append(f"同一服务被重复构造：{sorted(duplicates)}")
    for later, earlier in REQUIRED_BEFORE.items():
        if earlier not in order or later not in order:
            problems.append(f"缺少构造：{later} 或 {earlier}")
            continue
        if order.index(earlier) > order.index(later):
            problems.append(f"{earlier} 必须先于 {later} 构造")
    return problems


def check_helper_removed() -> list[str]:
    source = APP.read_text(encoding="utf-8")
    if "def _initialize(" in source:
        return ["组合根保留了未使用的 _initialize 辅助函数"]
    return []


CHECKS = (
    ("初始化播报", check_logging),
    ("初始化接收者", check_receivers),
    ("装配顺序", check_order),
    ("无残留辅助函数", check_helper_removed),
)


def main() -> int:
    failures: list[tuple[str, str]] = []
    for name, check in CHECKS:
        for problem in check():
            failures.append((name, problem))
    if not failures:
        print(f"组合根启动契约审查通过：{len(CHECKS)} 项检查")
        return 0
    print(f"组合根启动契约越界 {len(failures)} 处：")
    for name, problem in failures:
        print(f"  [{name}] {problem}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
