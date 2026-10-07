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
import copy
import io
import re
import subprocess
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ("game", "launch", "message")
SKIP_PARTS = {"__pycache__", ".venv", ".git"}

#: 中日韩统一表意文字（含扩展 A 与兼容区）。用来判「这个标识符是不是中文写的」。
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

#: 机器绝对路径：`C:\Users\<谁>\…`、`/Users/<谁>/…`、`/home/<谁>/…`。
MACHINE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+|[\\/]Users[\\/][^\\/\s\"']+[\\/]|/home/[^/\s\"']+/)"
)
#: 判据自己要把这个形状写出来当例子（正则与 docstring），所以只能放过它自己。
MACHINE_PATH_ALLOWLIST = {Path("tools/架构审查/检查边界.py")}


def _has_cjk(text: str) -> bool:
    return bool(CJK.search(text))

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

    `tools` 是维护期代码（审查、测量）。运行期依赖它会把维护脚本拖进
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


#: 字段取值校验的唯一实现（见 `系统架构.md` 第四节）。命令层不得导入核心服务，
#: 所以 `game/cmd` 里的副本按边界留在本地，不在本检查范围内。
FIELD_VALIDATOR_PATH = Path("game/core/data/fields.py")


def _erase_raise_target(node: ast.AST) -> ast.AST:
    """把所有 `raise X(...)` 的 X 抹成同一个占位符：唯一的差异就是抛哪个异常。"""

    class Erase(ast.NodeTransformer):
        def visit_Raise(self, item: ast.Raise) -> ast.AST:
            if isinstance(item.exc, ast.Call):
                item.exc.func = ast.Name(id="E", ctx=ast.Load())
            return self.generic_visit(item)

    return Erase().visit(node)


def _body_shape(node: ast.FunctionDef) -> str:
    """函数体（去掉文档字符串）的结构签名。深拷贝，别改到原节点。"""

    shell = copy.deepcopy(node)
    shell.body = [
        item for item in shell.body
        if not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant))
    ]
    shell.name = "_"
    shell.decorator_list = []
    shell.returns = None
    shell.args = ast.arguments(
        posonlyargs=[], args=[], vararg=None, kwonlyargs=[],
        kw_defaults=[], kwarg=None, defaults=[],
    )
    return ast.dump(
        _erase_raise_target(ast.fix_missing_locations(shell)), annotate_fields=False
    )


def _field_validator_shapes() -> dict[str, str]:
    """共享字段校验的形状。**从实现自己算**，判据与实现同源，不会各自漂移。"""

    return {
        node.name: _body_shape(node)
        for node in _parse(PROJECT_ROOT / FIELD_VALIDATOR_PATH).body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }


def check_field_validators_are_shared() -> list[Finding]:
    """字段取值校验不得各服务再抄一遍（见 `系统架构.md` 第四节）。

    正整数 / 非负整数 / 对象 / 非空文本 / 严格文本 / 布尔 / 数值 / 数组这几个判定
    原先在服务里各抄一份，严口径量下来 146 处，彼此只差抛哪个异常——`bool` 是
    `int` 的子类要先排除这一条就抄了 57 遍，修好一处不会传给另外 56 处。现在只有
    `game/core/data/fields.py` 一份实现，域错误用 `error=` 传。

    判定用**整个函数体的形状**是否与共享实现逐节点相同，不用「体里有没有某条
    `raise`」——`_sequence`（数组+非空）与 `_speech`（还查键集合）体里都含有一条
    同消息的 raise，那是不相干的校验器，按消息判会误报。委托式的一行包装体形状
    不同，因此不会报警——那正是允许的写法。
    """

    lookup = {shape: name for name, shape in _field_validator_shapes().items()}
    if not lookup:
        return [
            Finding(
                "字段校验重写",
                FIELD_VALIDATOR_PATH,
                1,
                "共享实现里认不出任何校验函数，检查无从判定",
            )
        ]
    findings: list[Finding] = []
    for root in ("game/core", "game/features"):
        for path in _python_files(root):
            relative = _relative(path)
            if relative.as_posix() == FIELD_VALIDATOR_PATH.as_posix():
                continue
            for node in ast.walk(_parse(path)):
                if not isinstance(node, ast.FunctionDef):
                    continue
                if [item.arg for item in node.args.args][:2] != ["value", "label"]:
                    continue
                helper = lookup.get(_body_shape(node))
                if helper:
                    findings.append(
                        Finding(
                            "字段校验重写",
                            relative,
                            node.lineno,
                            f"{node.name} 又写了一遍 {helper}；改用 "
                            f"game.core.data 的 {helper}，域错误用 error= 传",
                        )
                    )
    return findings


# 组合根由名字装载，静态导入看不见它（见 系统架构.md 第四节）。这里只列「确实没有
# 任何导入方、也确实该留」的模块；新增一条都要写清理由。
UNREFERENCED_MODULE_ALLOWLIST = {
    Path("game/app.py"): "唯一组合根，由 launch 侧按名字装载",
}


def _module_dotted(path: Path) -> str:
    return ".".join(path.relative_to(PROJECT_ROOT).with_suffix("").parts)


def _resolve_from(node: ast.ImportFrom, package: str) -> str:
    """把 `from …` 解析成被导入模块的全名。

    `from .utils import X` 里 `node.module` 只有 `utils`，不按包解析成全名，
    就没法和 `game.cmd.通用.查看.utils` 对上，那样每个模块都会看着像孤儿。
    """

    base = node.module or ""
    if not node.level:
        return base
    parts = package.split(".")
    # level=1 指当前包，level=2 再上一层。
    parts = parts[: len(parts) - (node.level - 1)]
    return ".".join(parts + ([base] if base else []))


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """找出文档字符串节点。

    只是说明，不算引用。这条很要紧：本检查自己的 docstring 就举了
    `game/cmd/通用/查看/combat.py` 当例子，若不排除，它会用自己的说明把那个
    孤儿模块「引用」掉，于是永远抓不到——第一版就是这样漏报的。
    """

    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def _referenced_modules() -> tuple[set[str], dict[Path, str]]:
    """返回（被静态导入的模块全名，各文件非 docstring 的字符串字面量文本）。"""

    imported: set[str] = set()
    strings: dict[Path, str] = {}
    for root in ("game", "tools", "launch", "message", "tests"):
        if not (PROJECT_ROOT / root).is_dir():
            continue
        for path in _python_files(root):
            try:
                tree = _parse(path)
            except (SyntaxError, UnicodeDecodeError):
                continue  # 解析不了的文件由 main 单独报，不在这里重复
            package = _package_of(path)
            docstrings = _docstring_nodes(tree)
            literals: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imported.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    base = _resolve_from(node, package)
                    if base:
                        imported.add(base)
                        for alias in node.names:
                            imported.add(f"{base}.{alias.name}")
                elif (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstrings
                ):
                    literals.append(node.value)
            strings[path] = "\n".join(literals)
    return imported, strings


def check_ascii_identifiers() -> list[Finding]:
    """游戏代码的标识符不得含中文。

    负责人口径（第 80 轮）：**`game/` 里不写中文标识符**——不是所有机器都吃得下中文写的
    代码。注释、文档串、给玩家看的文案、以及 JSON 里的数据键照旧是中文；**只有标识符**
    （变量、函数、类、参数、导入名）必须英文。

    数据键（如 `"读取数值"`、`json.get("能力")`）是**字符串**，不在此列；它们与数据层
    一一对应，改名要连着 JSON 一起动。渲染器因此不拼 `f"_ability_{能力名}"`，改成查
    `card_text.ABILITY_RENDERERS` 这张显式表。

    只扫 `game/`：`tools/` 与 `tests/` 是开发期脚本，允许中文标识符。
    """

    findings: list[Finding] = []
    for path in _python_files("game"):
        relative = _relative(path)
        source = path.read_text(encoding="utf-8")
        try:
            tokens = tokenize.generate_tokens(io.StringIO(source).readline)
            for token in tokens:
                if token.type == tokenize.NAME and _has_cjk(token.string):
                    findings.append(
                        Finding(
                            "中文标识符",
                            relative,
                            token.start[0],
                            f"{token.string} 是标识符；注释与文案可以中文，名字不行",
                        )
                    )
        except (tokenize.TokenError, IndentationError) as exc:
            findings.append(Finding("无法解析", relative, 1, str(exc)))
    return findings


def check_file_encodings() -> list[Finding]:
    """源码与数据文件不得带 UTF-8 BOM。

    BOM 会让 `ast.parse` 与 `json.loads` **直接报错**（不是警告）——`tools/说明.md` 里
    记过这条教训：造探针文件时用 `Set-Content -Encoding UTF8` 写出的 BOM 让整支审查
    当场死掉，看着像「查出了违规」。第 82 轮清出 4 个带 BOM 的文件（2 个数据说明、
    2 个工具脚本）。
    """

    findings: list[Finding] = []
    for 根 in ("game", "tools", "tests", "launch", "message", "data"):
        目录 = PROJECT_ROOT / 根
        if not 目录.is_dir():
            continue
        for path in sorted(目录.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".json", ".md"}:
                continue
            if any(段 in SKIP_PARTS for 段 in path.parts):
                continue
            try:
                with path.open("rb") as handle:
                    开头 = handle.read(3)
            except OSError:
                continue
            if 开头 == b"\xef\xbb\xbf":
                findings.append(
                    Finding(
                        "UTF-8 BOM",
                        _relative(path),
                        1,
                        "BOM 会让 ast.parse / json.loads 直接报错；存成无 BOM 的 UTF-8",
                    )
                )
    return findings


def check_duplicate_definitions() -> list[Finding]:
    """同一模块不得重复定义同名顶层函数或类。

    重复定义不会报错，**后一份静默覆盖前一份**——`game/core/combat/templates.py` 有
    104 行（`_materialize` / `order_diff` / `restore_reference` 三个函数与两个私有类）
    被整段复制了两遍，第一份是死代码，而「改了第一份却不生效」这类事故不会有任何提示。
    同一个名字在模块顶层出现两次就是病，不区分两份是否逐字相同。
    """

    findings: list[Finding] = []
    for root in SOURCE_ROOTS:
        目录 = PROJECT_ROOT / root
        if not 目录.is_dir():
            continue
        for path in sorted(目录.rglob("*.py")):
            if any(段 in SKIP_PARTS for 段 in path.parts):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            位置: dict[str, int] = {}
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                先前 = 位置.get(node.name)
                if 先前 is not None:
                    findings.append(
                        Finding(
                            "重复定义",
                            _relative(path),
                            node.lineno,
                            f"{node.name} 在第 {先前} 行已定义过，这一份会静默覆盖它",
                        )
                    )
                else:
                    位置[node.name] = node.lineno
    return findings


def check_unreferenced_modules() -> list[Finding]:
    """不得留下无人引用的模块。

    典型来历：重构把调用方接到新实现上，旧实现留在原处。它不再被读到，却仍然长得
    像一套基础设施——`game/cmd/通用/查看/combat.py` 就这样冒充了二十多个提交的
    「第二套战斗渲染器」，让人对着两套实现判断该统一到哪一套，而正确处置是直接删。
    死代码不会报错，只能靠查引用发现。

    「被引用」取宽，宁可漏报也不误伤活模块，任一条成立即可：静态导入到该模块全名；
    别处的字符串字面量里出现该模块全名或文件名（动态装载与配置表走这条路）。
    """

    imported, strings = _referenced_modules()
    findings: list[Finding] = []
    for path in _python_files("game"):
        if path.name in {"__init__.py", "__main__.py"}:
            continue  # 包入口与脚本入口本来就不必被导入
        relative = _relative(path)
        if relative in UNREFERENCED_MODULE_ALLOWLIST:
            continue
        if _module_dotted(path) in imported:
            continue
        referenced = False
        for owner, text in strings.items():
            if owner == path:
                continue
            if _module_dotted(path) in text or path.name in text:
                referenced = True
                break
        if referenced:
            continue
        findings.append(
            Finding(
                "无人引用的模块",
                relative,
                1,
                f"{_module_dotted(path)} 没有任何导入方；确认是死代码就直接删，"
                f"确实要留就写进 UNREFERENCED_MODULE_ALLOWLIST 并写明理由",
            )
        )
    return findings


def check_hardcoded_machine_paths() -> list[Finding]:
    """源码里不得写死某一台机器的绝对路径。

    写死路径不会报错，只是在别人机器上**改到空气**或者建到别处——第 82 轮一次查出
    **17 支脚本**把项目根写成 `C:\\Users\\<别人>\\Desktop\\晓楠修仙`（那是上一台机器的
    位置），它们在本机跑起来会去读一个不存在的目录。同一批还有两处把临时目录写成
    `C:\\Users\\<谁>\\AppData\\Local\\Temp\\…`。

    项目根用 `pathlib.Path(__file__).resolve().parents[N]` 推，临时目录用
    `tempfile.gettempdir()`，两者都与机器无关。

    **只扫字符串字面量**：注释里出现这种路径（比如本检查的来历说明）是历史记录，不算病；
    代价是跨行拼起来的路径扫不到——真要拼路径，用 `pathlib` 就等于绕开了这个问题。
    """

    findings: list[Finding] = []
    for root in ("game", "tools", "tests", "launch", "message"):
        目录 = PROJECT_ROOT / root
        if not 目录.is_dir():
            continue
        for path in sorted(目录.rglob("*.py")):
            if SKIP_PARTS & set(path.parts):
                continue
            if _relative(path) in MACHINE_PATH_ALLOWLIST:
                continue
            try:
                tokens = list(
                    tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline)
                )
            except (tokenize.TokenError, IndentationError):
                continue  # 解析不了的交给 check_file_encodings / 主流程报
            for token in tokens:
                if token.type != tokenize.STRING:
                    continue
                命中 = MACHINE_PATH.search(token.string)
                if 命中 is None:
                    continue
                findings.append(
                    Finding(
                        "写死机器路径",
                        _relative(path),
                        token.start[0],
                        f"`{命中.group(0)}` 只在那一台机器上存在；项目根用 "
                        f"`pathlib.Path(__file__).resolve().parents[N]` 推，临时目录用 "
                        f"`tempfile.gettempdir()`",
                    )
                )
    return findings


def check_tracked_ignored_files() -> list[Finding]:
    """被 `.gitignore` 忽略的文件不得留在索引里。

    第 87 轮盘出来的：`certs/` 早就写进了 `.gitignore`，但四个文件仍在索引里被跟踪——
    其中是**域名证书的私钥**。忽略规则与索引各说各话时，谁也不会报错：规则看着守住了，
    东西照旧进库。这条判据把两者对一遍（`git ls-files -i -c` 就是「已跟踪且被忽略」）。
    """

    try:
        done = subprocess.run(
            ["git", "ls-files", "-i", "-c", "--exclude-standard"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:  # 没有 git 时不判：这是维护审查，不是运行期契约
        return []
    if done.returncode != 0:
        return []
    return [
        Finding(
            "忽略文件入库",
            Path(line.strip()),
            0,
            "`.gitignore` 说它不该入库（`git rm --cached` 保留磁盘文件）",
        )
        for line in (done.stdout or "").splitlines()
        if line.strip()
    ]


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
    ("无人引用的模块", check_unreferenced_modules),
    ("中文标识符", check_ascii_identifiers),
    ("文件编码", check_file_encodings),
    ("重复定义", check_duplicate_definitions),
    ("写死机器路径", check_hardcoded_machine_paths),
    ("字段校验重写", check_field_validators_are_shared),
    ("忽略文件入库", check_tracked_ignored_files),
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
