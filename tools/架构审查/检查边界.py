"""架构边界审查。

把 `系统架构.md` 与 `微服务边界规范.md` 已经声明的禁止项变成可执行检查。
本脚本属于维护审查，不进入游戏启动流程，也不被 `game` 依赖。

用法：

```powershell
.venv/Scripts/python.exe -X utf8 tools/架构审查/检查边界.py
```

退出码 0 表示全部通过；1 表示存在越界，并在标准输出列出文件与行号。
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ("game", "launch", "message")
SKIP_PARTS = {"__pycache__", ".venv", ".git"}

# 实现模块不得被跨服务导入（见 微服务边界规范.md 第二节）。
INTERNAL_MODULES = {
    "engine",
    "models",
    "runtime",
    "schema",
    "selection",
    "loading",
    "files",
    "storage",
    "mechanics",
}
# 绑定模块属于该服务自己的运行实现，只在服务内部导入。
BOUND_INTERNAL_MODULES = {"build_terms", "catalog", "damage", "elements", "executors", "presentation", "report"}

# 只有这两个装载边界允许运行时动态导入（见 微服务边界规范.md 第八节）。
DYNAMIC_IMPORT_ALLOWLIST = {
    Path("game/cmd/__init__.py"),
    Path("launch/load_router.py"),
}
# 框架不得静态引用应用层（见 系统架构.md 第四节）。
FRAMEWORK_ROOTS = ("launch", "message")

# 数据原则：Python 只读取引导文件，不得硬编码 data 目录布局。
DATA_PATH_ALLOWLIST = {Path("game/core/data/files.py"), Path("game/core/data/loading.py")}


@dataclass(frozen=True)
class Finding:
    rule: str
    path: Path
    line: int
    detail: str

    def render(self) -> str:
        return f"[{self.rule}] {self.path}:{self.line}  {self.detail}"


def _relative(path: Path) -> Path:
    return path.relative_to(PROJECT_ROOT)


def _python_files(root: str) -> Iterator[Path]:
    for path in (PROJECT_ROOT / root).rglob("*.py"):
        if SKIP_PARTS & set(path.parts):
            continue
        yield path


def _parse(path: Path) -> ast.Module:
    """读并解析，**带上文件名**。

    `ast.parse` 不带 `filename` 时，出错只会说 `<unknown>`，据此找不到是哪个文件。
    """

    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.AST) -> Iterator[tuple[int, str]]:
    """产出 (行号, 被导入的模块名)。"""

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module


def _package_of(path: Path) -> str:
    """返回微服务包名，例如 game/core/combat/engine.py -> game.core.combat。"""

    relative = path.relative_to(PROJECT_ROOT)
    parts = relative.parts
    if len(parts) >= 3 and parts[0] == "game" and parts[1] in {"core", "features"}:
        return ".".join(parts[:3])
    return ".".join(parts[:-1])


def check_dynamic_imports() -> list[Finding]:
    findings: list[Finding] = []
    for root in SOURCE_ROOTS:
        for path in _python_files(root):
            relative = _relative(path)
            if relative in DYNAMIC_IMPORT_ALLOWLIST:
                continue
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id == "__import__":
                        names.append("__import__")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr == "import_module":
                        names.append("import_module")
                elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
                    names.extend(alias.name for alias in node.names if alias.name == "import_module")
                if names:
                    findings.append(
                        Finding(
                            "动态导入越界",
                            relative,
                            node.lineno,
                            f"{names[0]} 只能出现在 game/cmd/__init__.py 与 launch/load_router.py",
                        )
                    )
    return findings


def check_framework_dependency() -> list[Finding]:
    findings: list[Finding] = []
    for root in FRAMEWORK_ROOTS:
        for path in _python_files(root):
            tree = _parse(path)
            for line, module in _imports(tree):
                top = module.split(".")[0]
                if top in {"game", "tools"}:
                    findings.append(
                        Finding(
                            "框架反向依赖",
                            _relative(path),
                            line,
                            f"launch/message 不得静态引用 {top}",
                        )
                    )
    return findings


def check_core_internal_imports() -> list[Finding]:
    """核心与玩法服务只能从其他微服务包顶层导入。"""

    findings: list[Finding] = []
    for root in ("game/core", "game/features"):
        for path in _python_files(root):
            relative = _relative(path)
            owner = _package_of(path)
            tree = _parse(path)
            for line, module in _imports(tree):
                if not module.startswith("game.core."):
                    continue
                parts = module.split(".")
                if len(parts) < 4:
                    continue
                target = ".".join(parts[:3])
                if target == owner:
                    continue
                leaf = parts[3]
                if leaf in INTERNAL_MODULES or leaf in BOUND_INTERNAL_MODULES:
                    findings.append(
                        Finding(
                            "跨服务导入内部实现",
                            relative,
                            line,
                            f"{module} 属于 {target} 的内部实现，应只导入其包顶层",
                        )
                    )
    return findings


def check_cmd_core_dependency() -> list[Finding]:
    """命令层不得直接导入核心服务（见 `微服务边界规范.md` 第三节）。

    命令层只消费玩法层已经给出的业务事实；需要核心能力时由玩法层代为取得、
    把结果交出来。这条规则原先**没有任何检查**——`check_core_internal_imports`
    只扫 `game/core` 与 `game/features`，`game/cmd` 不在范围内，于是「查看」曾经
    直接导入战斗核心的渲染器（`game.core.combat.card_text`）而长期无人发现。
    """

    findings: list[Finding] = []
    for path in _python_files("game/cmd"):
        relative = _relative(path)
        tree = _parse(path)
        for line, module in _imports(tree):
            if module == "game.core" or module.startswith("game.core."):
                findings.append(
                    Finding(
                        "命令层导入核心服务",
                        relative,
                        line,
                        f"命令层不得导入 {module}；应由玩法层代为取得后交出结果",
                    )
                )
    return findings


def check_data_layout_hardcoding() -> list[Finding]:
    """业务服务不得硬编码 data 目录布局。"""

    findings: list[Finding] = []
    for root in SOURCE_ROOTS:
        for path in _python_files(root):
            relative = _relative(path)
            if relative in DATA_PATH_ALLOWLIST:
                continue
            for number, raw in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                stripped = raw.strip()
                if stripped.startswith("#"):
                    continue
                if '"data/' in stripped or "'data/" in stripped or '"data\\\\' in stripped:
                    findings.append(
                        Finding(
                            "硬编码数据目录",
                            relative,
                            number,
                            "只允许 game/core/data 读取 data 目录布局",
                        )
                    )
    return findings


def check_single_json_reader() -> list[Finding]:
    """不得出现第二套 JSON Reader。

    红线是"从磁盘读文件"。数据库状态反序列化、HTTP 响应解析和 QQ 回调体解析
    都不是读取正式 JSON，不属于本规则管辖。
    """

    findings: list[Finding] = []
    for root in SOURCE_ROOTS:
        for path in _python_files(root):
            relative = _relative(path)
            if relative.parts[:3] == ("game", "core", "data"):
                continue
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                detail: str | None = None
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    owner = node.func.value
                    if isinstance(owner, ast.Name) and owner.id == "json":
                        if node.func.attr == "load" and node.args:
                            detail = "json.load 直接读取文件对象"
                        elif node.func.attr == "loads":
                            first = node.args[0] if node.args else None
                            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                                if first.value.strip().endswith(".json"):
                                    detail = f"json.loads 内联 JSON 文件内容 {first.value[:40]}"
                if detail is None and isinstance(node, ast.Constant) and isinstance(node.value, str):
                    text = node.value.strip()
                    if text.endswith(".json") and "/" in text and "data" in text:
                        detail = f"硬编码 JSON 文件路径 {text[:60]}"
                if detail:
                    findings.append(
                        Finding("第二套 JSON 读取", relative, node.lineno, detail)
                    )
    return findings


def check_service_doc_coverage() -> list[Finding]:
    """每个微服务包必须提供 __init__.py、service.py 与 说明.md。

    `contracts.py` 是契约定义位置，不是必备文件：只做「再导出核心契约」或
    「只读取展示文本」的玩法包没有自己的新类型，就不应为了凑齐文件而造出
    无人消费的类型——那会成为死代码，并改变命令层原有的异常语义。
    """

    findings: list[Finding] = []
    for root in ("game/core", "game/features"):
        for directory in sorted((PROJECT_ROOT / root).iterdir()):
            if not directory.is_dir() or directory.name == "__pycache__":
                continue
            for required in ("__init__.py", "service.py", "说明.md"):
                if not (directory / required).is_file():
                    findings.append(
                        Finding(
                            "微服务包结构不完整",
                            _relative(directory),
                            0,
                            f"缺少 {required}",
                        )
                    )
    return findings


def check_console_boundary() -> list[Finding]:
    """维护者入口的例外边界（见 game/cmd/说明.md）。

    `game/cmd/后台` 可以保留自身认证、短期存储、站点与 HTML 投影，但不得读取
    游戏规则、玩家资产或战斗事实，也不得使用游戏数据库。例外只覆盖这些职责。
    """

    findings: list[Finding] = []
    console_root = PROJECT_ROOT / "game" / "cmd" / "后台"
    if not console_root.is_dir():
        return findings
    for path in console_root.rglob("*.py"):
        if SKIP_PARTS & set(path.parts):
            continue
        relative = _relative(path)
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for line, module in _imports(tree):
            # 维护者入口不读游戏规则、玩家资产、战斗事实，也不使用游戏配置：
            # 消息观察库路径由控制台自己从框架自定义项解析。
            if module == "game.config" or module.startswith(
                ("game.core", "game.features", "game.startup")
            ):
                findings.append(
                    Finding(
                        "后台越界读取游戏",
                        relative,
                        line,
                        f"维护者入口不得导入 {module}",
                    )
                )
        for number, raw in enumerate(source.splitlines(), start=1):
            if "game_config.database.path" in raw:
                findings.append(
                    Finding(
                        "后台使用游戏数据库",
                        relative,
                        number,
                        "维护者入口只能使用 RUNTIME_LOG_DATABASE_PATH",
                    )
                )
    return findings


def check_core_upward_dependency() -> list[Finding]:
    """核心服务不得引用 `features` 或 `cmd`（见 `微服务边界规范.md` 第三节）。

    依赖方向是单向的：`cmd -> features -> core`。核心反过来引用上层，等于把玩法与
    命令语义拖进公共地基，「核心可被任何玩法复用」也就不再成立。

    `game/app.py` 是组合根，它**本来就要**导入 features；本规则只扫 `game/core`。
    """

    findings: list[Finding] = []
    for path in _python_files("game/core"):
        relative = _relative(path)
        tree = _parse(path)
        for line, module in _imports(tree):
            for upper in ("game.features", "game.cmd"):
                if module == upper or module.startswith(upper + "."):
                    findings.append(
                        Finding(
                            "核心引用上层",
                            relative,
                            line,
                            f"核心服务不得引用 {module}；方向只能是 cmd -> features -> core",
                        )
                    )
    return findings


def check_core_namespace() -> list[Finding]:
    """`game/core/__init__.py` 只保留命名空间，不转发具体服务。

    见 `系统架构.md` 第四节、`微服务边界规范.md` 第三节。它是「不许有第二套门面」
    的守卫：这里一旦开始转发，调用方就多出一条与「从各核心包顶层导入」并行的路径，
    边界随之失效。相对导入也算转发——`from .pool import …` 转的就是核心子包。
    """

    findings: list[Finding] = []
    path = PROJECT_ROOT / "game" / "core" / "__init__.py"
    if not path.is_file():
        return findings
    relative = _relative(path)
    tree = _parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "game.core" or alias.name.startswith("game.core."):
                    findings.append(
                        Finding("核心命名空间转发服务", relative, node.lineno,
                                f"不得在此导入 {alias.name}；具体服务从各自包顶层导入")
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").startswith("game.core"):
                target = "." * node.level + (node.module or "")
                findings.append(
                    Finding("核心命名空间转发服务", relative, node.lineno,
                            f"不得在此转发 {target}；具体服务从各自包顶层导入")
                )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(item, ast.Name) and item.id == "__all__" for item in targets):
                continue
            value = node.value
            if not (isinstance(value, ast.List) and not value.elts):
                findings.append(
                    Finding("核心命名空间转发服务", relative, node.lineno,
                            "__all__ 必须为空：本包是命名空间，不导出具体服务")
                )
    return findings


def check_game_tools_dependency() -> list[Finding]:
    """`game` 不得导入 `tools`（见 `系统架构.md` 第四节）。

    `tools` 是维护期代码（审查、测量、一次性迁移）。运行期依赖它会把维护脚本拖进
    游戏进程，也会把「tools 可以访问内部实现」这条单向许可变成双向耦合。
    """

    findings: list[Finding] = []
    for path in _python_files("game"):
        relative = _relative(path)
        tree = _parse(path)
        for line, module in _imports(tree):
            if module == "tools" or module.startswith("tools."):
                findings.append(
                    Finding("运行期依赖 tools", relative, line,
                            f"game 不得导入 {module}；维护代码不进运行期")
                )
    return findings


def check_contracts_file_purpose() -> list[Finding]:
    """`contracts.py` 只在包内确实定义了新类型时才建立。

    见 `微服务边界规范.md` 第二节：`contracts.py` 不是必备文件，只做「再导出核心契约」
    的它会是死代码，还会改掉命令层原有的异常语义（玩法再导出核心错误时不必自建文件）。
    """

    findings: list[Finding] = []
    for root in ("game/core", "game/features"):
        for path in _python_files(root):
            if path.name != "contracts.py":
                continue
            tree = _parse(path)
            defines_type = any(
                isinstance(node, ast.ClassDef)
                or (
                    isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and "TypeAlias" in ast.unparse(node.annotation)
                )
                for node in tree.body
            )
            if not defines_type:
                findings.append(
                    Finding("contracts.py 没有定义新类型", _relative(path), 1,
                            "只再导出核心契约的 contracts.py 是死代码，应当删除")
                )
    return findings


#: 命令层里只允许做纯适配的模块名（见 `微服务边界规范.md` 第三节）。
COMMAND_ADAPTER_MODULES = frozenset({"reply.py", "input.py"})

#: 组合根 `game/app.py` 的入口函数。适配模块不得取得它们。
COMPOSITION_ROOT_ENTRIES = frozenset({
    "build_game_services",
    "current_game_services",
    "initialize_game_services",
    "shutdown_game_services",
})


def check_command_adapter_purity() -> list[Finding]:
    """命令层的 `reply.py` / `input.py` 是纯适配模块，不得取得组合根服务。

    见 `微服务边界规范.md` 第三节。它们一旦拿到服务，就会开始从状态版本、编号关系
    或资产明细里推断业务事实——而结论必须由玩法公共结果给出。

    只按**模块名**判，不按内容猜：命令组件的回调写在 `__init__.py`，那里本来就要
    取服务；`reply.py`/`input.py` 是可选存在的适配模块，存在就必须是纯的。
    """

    findings: list[Finding] = []
    for path in _python_files("game/cmd"):
        if path.name not in COMMAND_ADAPTER_MODULES:
            continue
        relative = _relative(path)
        tree = _parse(path)
        for line, module in _imports(tree):
            if module == "game.app" or module.startswith("game.app."):
                findings.append(
                    Finding("适配模块取得组合根", relative, line,
                            f"reply.py/input.py 不得导入 {module}；结论由玩法公共结果给出")
                )
        for node in ast.walk(tree):
            name = ""
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            if name in COMPOSITION_ROOT_ENTRIES:
                findings.append(
                    Finding("适配模块取得组合根", relative, node.lineno,
                            f"reply.py/input.py 不得调用 {name}；结论由玩法公共结果给出")
                )
    return findings


#: 目录遍历调用。核心只允许 JSON 读取器按读取规则遍历，其余代码一律走数据服务。
DIRECTORY_TRAVERSAL_CALLS = frozenset({
    "glob", "rglob", "iterdir", "walk", "scandir", "listdir",
})

#: 允许遍历目录的位置。`files.py` 是唯一按读取规则遍历正式 JSON 的地方；
#: 后台控制台的 `media.py` 清理的是它自己的媒体目录（`/game-console/media/`），
#: 不是游戏数据，属于 `game/cmd/说明.md` 里那条后台例外。
DIRECTORY_TRAVERSAL_ALLOWLIST = {
    Path("game/core/data/files.py"),
    Path("game/cmd/后台/天道后台/media.py"),
}


def check_data_directory_traversal() -> list[Finding]:
    """业务代码不得自己遍历或拆解 data 目录（见 `微服务边界规范.md` 第四节）。

    读取正式 JSON 只有一条路：`JsonDataService` 按 `读取规则.json` 建立实体索引与
    资源池，其他服务按数据集名、实体类别或资源池查询。自己 `glob`/`iterdir` 会绕开
    规则匹配与归档，等于长出第二套数据入口。

    本规则与「硬编码数据目录」（拦路径字面量）、「第二套 JSON 读取」（拦 `json.load`）
    合起来，才覆盖规范第四节「不得在自身代码中遍历或拆解数据目录」整句。
    `tools` 不在扫描范围——它按许可能访问内部实现。
    """

    findings: list[Finding] = []
    for path in _python_files("game"):
        relative = _relative(path)
        if relative in DIRECTORY_TRAVERSAL_ALLOWLIST:
            continue
        tree = _parse(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            else:
                continue
            if name in DIRECTORY_TRAVERSAL_CALLS:
                findings.append(
                    Finding("遍历数据目录", relative, node.lineno,
                            f"不得自行 {name}；正式 JSON 只能由 game/core/data 按读取规则建立索引")
                )
    return findings


#: `random` 模块里可以用的东西：带种子的实例类型。其余（便捷函数与直接再导入）
#: 用的是全局无种子 RNG，结果不可复现——重现不了的平衡测量与语料对照等于没有。
RANDOM_ALLOWED = frozenset({"Random", "SystemRandom"})

#: 战斗引擎只允许在本包内被提到；`simulate_teams` 只允许在定义处与唯一入口处出现。
COMBAT_PACKAGE = Path("game/core/combat")
COMBAT_ENTRY_MODULE = Path("game/core/combat/service.py")
COMBAT_ENGINE_NAMES = frozenset({"BattleEngine"})
COMBAT_RUN_NAMES = frozenset({"simulate_teams"})

#: 评分与平衡模拟只属于 `tools`（见 `系统架构.md` 第一节第 4 条）。
#: **按名字判，不扫源码正文**——`generating` 里含 "rating"、五行相生的 `root_score`
#: 是战斗规则计算，扫正文会把它们全误报。
SCORING_NAME = re.compile(r"评分|平衡|(^|_)score($|_)|(^|_)scoring($|_)|(^|_)balance($|_)", re.I)


def check_random_seeding() -> list[Finding]:
    """随机必须走带种子的实例，不得用 `random` 模块的便捷函数。

    见 `微服务边界规范.md` 第五节「随机服务必须返回或接受种子，保证结果可复现」。
    `random.choice()` / `random.random()` 走的是全局 RNG：同一次运行里先后顺序会
    影响结果，换一次运行就对不上，重现不了的东西没法当基准。
    """

    findings: list[Finding] = []
    for path in _python_files("game"):
        relative = _relative(path)
        tree = _parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "random":
                for alias in node.names:
                    if alias.name not in RANDOM_ALLOWED:
                        findings.append(
                            Finding("随机未带种子", relative, node.lineno,
                                    f"不得再导入 random.{alias.name}；请用 random.Random(种子)")
                        )
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                if isinstance(owner, ast.Name) and owner.id == "random" \
                        and node.func.attr not in RANDOM_ALLOWED:
                    findings.append(
                        Finding("随机未带种子", relative, node.lineno,
                                f"不得调用 random.{node.func.attr}()；请用 random.Random(种子)")
                    )
    return findings


def check_combat_single_entry() -> list[Finding]:
    """战斗入口唯一：不得出现第二套战斗入口（见 `系统架构.md` 第四节）。

    这是硬条件，不给例外。唯一入口是 `game/core/combat/service.py` 的 `CombatService`；
    其余玩法只能注入 `CombatService` 并提交 `CombatRequest`。自己驱动 `BattleEngine`
    或直接调 `simulate_teams` 都会绕开它的装配、快照与战报协议。
    """

    findings: list[Finding] = []
    for path in _python_files("game"):
        relative = _relative(path)
        for node in ast.walk(_parse(path)):
            names: list[str] = []
            if isinstance(node, ast.Name):
                names.append(node.id)
            elif isinstance(node, ast.Attribute):
                names.append(node.attr)
            for name in names:
                if name in COMBAT_ENGINE_NAMES and COMBAT_PACKAGE not in relative.parents:
                    findings.append(
                        Finding("第二套战斗入口", relative, node.lineno,
                                f"不得在战斗包外使用 {name}；只能注入 CombatService")
                    )
                elif name in COMBAT_RUN_NAMES and relative not in {
                    COMBAT_ENTRY_MODULE, COMBAT_PACKAGE / "engine.py",
                }:
                    findings.append(
                        Finding("第二套战斗入口", relative, node.lineno,
                                f"不得直接调用 {name}；唯一入口是 CombatService")
                    )
    return findings


def check_scoring_outside_tools() -> list[Finding]:
    """评分、平衡模拟不得进入运行时（见 `系统架构.md` 第一节第 4 条、第四节）。

    「目录规范、发布校核、评分、平衡模拟和内容生成只属于 `tools`」，而「评分进入
    运行时」被明确列为架构错误。判据只取**目录名、模块名与顶层函数名**，不扫正文。
    """

    findings: list[Finding] = []
    for path in sorted((PROJECT_ROOT / "game").rglob("*")):
        if SKIP_PARTS & set(path.parts):
            continue
        relative = _relative(path)
        if path.is_dir() or path.suffix == ".py":
            if SCORING_NAME.search(path.stem):
                findings.append(
                    Finding("评分进入运行时", relative, 1,
                            "评分与平衡模拟只属于 tools；运行时不解释内容评分")
                )
        if path.suffix != ".py":
            continue
        for node in _parse(path).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and SCORING_NAME.search(node.name):
                findings.append(
                    Finding("评分进入运行时", relative, node.lineno,
                            f"顶层函数 {node.name} 属于评分/平衡模拟，应放 tools")
                )
    return findings


def _declares_mutable_dataclass(node: ast.ClassDef) -> bool:
    """裸 `@dataclass` 与 `@dataclass()` 都默认可变；只有 `frozen=True` 才是快照。"""

    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
            return True
        if isinstance(decorator, ast.Call):
            func = decorator.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name != "dataclass":
                continue
            for keyword in decorator.keywords:
                if keyword.arg == "frozen":
                    return not bool(getattr(keyword.value, "value", False))
            return True
    return False


def _runtime_types() -> dict[str, str]:
    """全库**可变运行对象**的名字 -> 所属包。

    必须全库取，不能按包取：`features/chakan_wupin` 里一个运行期模块都没有，
    而它要防的 `Fighter` 住在 `game/core/combat` ——按包取会把它整个跳过，
    检查看着通过、其实什么都没查。（这个坑是反向验证抓出来的。）
    """

    table: dict[str, str] = {}
    for root in ("game/core", "game/features"):
        for package in sorted((PROJECT_ROOT / root).iterdir()):
            if not package.is_dir() or SKIP_PARTS & set(package.parts):
                continue
            for module in sorted(package.glob("*.py")):
                if module.stem not in INTERNAL_MODULES | BOUND_INTERNAL_MODULES:
                    continue
                for node in _parse(module).body:
                    if isinstance(node, ast.ClassDef) and _declares_mutable_dataclass(node):
                        table[node.name] = _relative(package).as_posix()
    return table


def check_public_contracts_are_pure() -> list[Finding]:
    """公共契约与包顶层导出不得引用可变运行对象（见 `微服务边界规范.md` 第五节）。

    「不得返回 `Fighter`、`BattleContext`、`StatusState` 等可变运行对象」——规范举的
    这三个例子，正是 `game/core/combat/models.py` 里非 frozen 的那批。运行对象可变，
    递出去调用方就能原地改战斗事实，绕开事务与校验。

    只查 `contracts.py` 与包顶层 `__init__.py`：`service.py` 内部构造 prepared 快照
    是正常的，不该拦。契约正文里认名字（Name/Attribute），`__init__.py` 只认
    `__all__` 里的字符串——否则文档字符串里提到类型名也会误报。
    """

    runtime = _runtime_types()
    findings: list[Finding] = []
    for root in ("game/core", "game/features"):
        for package in sorted((PROJECT_ROOT / root).iterdir()):
            if not package.is_dir() or SKIP_PARTS & set(package.parts):
                continue
            contracts = package / "contracts.py"
            if contracts.is_file():
                relative = _relative(contracts)
                for node in ast.walk(_parse(contracts)):
                    label = ""
                    if isinstance(node, ast.Name):
                        label = node.id
                    elif isinstance(node, ast.Attribute):
                        label = node.attr
                    if label in runtime:
                        findings.append(
                            Finding(
                                "公共契约引用运行期对象", relative, node.lineno,
                                f"不得在公共契约里出现 {label}；它是 {runtime[label]} 的"
                                f"可变运行对象",
                            )
                        )
            init = package / "__init__.py"
            if init.is_file():
                relative = _relative(init)
                for node in _parse(init).body:
                    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                        continue
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    if not any(
                        isinstance(item, ast.Name) and item.id == "__all__"
                        for item in targets
                    ):
                        continue
                    if not isinstance(node.value, ast.List):
                        continue
                    for element in node.value.elts:
                        if isinstance(element, ast.Constant) and element.value in runtime:
                            findings.append(
                                Finding(
                                    "包顶层导出运行期对象", relative, node.lineno,
                                    f"不得再导出 {element.value}；它是 "
                                    f"{runtime[element.value]} 的可变运行对象",
                                )
                            )
    return findings


CHECKS = (
    ("动态导入越界", check_dynamic_imports),
    ("框架反向依赖", check_framework_dependency),
    ("跨服务导入内部实现", check_core_internal_imports),
    ("核心引用上层", check_core_upward_dependency),
    ("核心命名空间转发服务", check_core_namespace),
    ("运行期依赖 tools", check_game_tools_dependency),
    ("命令层导入核心服务", check_cmd_core_dependency),
    ("适配模块取得组合根", check_command_adapter_purity),
    ("公共契约引用运行期对象", check_public_contracts_are_pure),
    ("contracts.py 无新类型", check_contracts_file_purpose),
    ("硬编码数据目录", check_data_layout_hardcoding),
    ("遍历数据目录", check_data_directory_traversal),
    ("第二套 JSON 读取", check_single_json_reader),
    ("随机未带种子", check_random_seeding),
    ("第二套战斗入口", check_combat_single_entry),
    ("评分进入运行时", check_scoring_outside_tools),
    ("微服务包结构", check_service_doc_coverage),
    ("后台例外边界", check_console_boundary),
)


def main() -> int:
    all_findings: list[Finding] = []
    for name, check in CHECKS:
        try:
            all_findings.extend(check())
        except SyntaxError as exc:
            # 解析不了的文件不能让整支审查死掉：那会把后面所有检查一起藏起来，
            # 而「审查通过」正是大家据以放心的东西。带 BOM 的 UTF-8 源码就会这样。
            location = Path(str(exc.filename or "?"))
            try:
                location = _relative(location)
            except ValueError:
                pass  # 不在工程内（例如 `<unknown>`），原样保留
            all_findings.append(
                Finding(
                    name,
                    location,
                    int(exc.lineno or 0),
                    f"无法解析：{exc.msg}（源码必须是无 BOM 的 UTF-8）",
                )
            )
    if not all_findings:
        print(f"架构边界审查通过：{len(CHECKS)} 项检查")
        return 0
    print(f"架构边界越界 {len(all_findings)} 处：")
    for finding in sorted(all_findings, key=lambda item: (item.rule, str(item.path), item.line)):
        print(f"  {finding.render()}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
