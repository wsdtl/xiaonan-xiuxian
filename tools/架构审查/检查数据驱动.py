"""JSON 驱动完整性审查。

JSON 是这个项目规则与内容的唯一主体，因此"声明的数据是否真有人读"和
"字段契约是否被统一校验"是数据层的核心健康指标。本脚本检查：

1. **大类布局**：顶层是七大类，组件清单在第二层（组件名与大类同名时不再多一层）。
   扫描目录、组件清单、注册路径三者要互相对得上；大类里不许留下既不是四类目录、
   也不是已登记组件的空壳目录。
2. **组件说明要写功能**：每个组件的 `说明.md` 必须有一节 `## 功能`，按点分类，且每条引用的
   依据文件真的存在（说明与设计脱节是同一类病）。
3. **契约住错了面**：字段契约是**裁定参数**，按 `data/说明.md` 的目录约定该住
   `定义/` 或 `规则/`；混进 `内容/`（实体与资源池）或 `展示/`（文本与界面）会让
   「内容目录只放实体」这条约定失效。
4. **无消费者数据集**：在 `组件.json` 声明并被启动加载，却在 `game/` 中没有任何
   代码引用的数据集。它们会被校验通过并进入快照，但改动它们不影响游戏。
5. **无消费者池**：登记为池但从未被任何服务按池名引用。
6. **字段契约覆盖率**：有多少数据文件自带字段契约（`必填字段` / `可选字段` /
   `字段` + `类型`），其余只能靠手写校验器保护。
7. **手写校验规模**：跨服务重复定义的字段校验辅助数量，作为"schema 未统一"
   的量化指标。

属于数据维护审查，不进入游戏启动流程。

用法：

```powershell
.venv/Scripts/python.exe -X utf8 tools/架构审查/检查数据驱动.py
```

退出码 0 表示全部通过；1 表示存在大类布局问题、组件说明问题、契约住错面、无消费者数据或池。
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import sys
from collections import Counter

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA = PROJECT_ROOT / "data"
GAME = PROJECT_ROOT / "game"

# 字段校验辅助的命名形态；用于统计手写校验规模。
VALIDATOR_NAME = re.compile(
    r"^_(mapping|text|texts|number|numbers|integer|positive_int|positive_number"
    r"|sequence|strings|object|list|choice|item_count|required_text)\w*$"
)


def _game_source() -> str:
    """全部游戏源码文本，用于判断数据集名是否被引用。"""

    parts: list[str] = []
    for path in GAME.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _declared() -> dict[str, dict[str, object]]:
    """返回 数据集名 -> {组件集合, 是否有实体类别}。"""

    declared: dict[str, dict[str, object]] = {}
    for manifest in DATA.rglob("组件.json"):
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        component = str(raw.get("组件") or manifest.parent.name)
        for rule in raw.get("读取规则", []):
            name = rule.get("数据集")
            if not name:
                continue
            entry = declared.setdefault(
                str(name), {"components": set(), "entity": False}
            )
            entry["components"].add(component)  # type: ignore[union-attr]
            if rule.get("实体类别"):
                entry["entity"] = True
    return declared


四类面 = ("定义", "规则", "内容", "展示")


def check_category_layout() -> list[str]:
    """`data/` 的大类布局：顶层是大类，组件清单在第二层。

    `data/说明.md` 的口径（第 78 轮）：顶层收成七大类，大类里放组件；**组件名与大类同名时
    不再多一层**（`基础`、`世界`、`角色`、`战斗`、`宗门` 五个组件的面直接住在大类目录下），
    于是「大类既可以是组件，也可以装组件」。

    这里把三件事实对齐：读取入口的扫描目录、每个组件的清单、清单里注册的路径。再加一条
    空壳判据——大类里出现的目录，要么是四类面之一，要么是被扫描目录登记过的组件。
    """

    problems: list[str] = []
    入口们 = sorted(DATA.glob("*/读取规则.json")) + sorted(DATA.glob("*/*/读取规则.json"))
    if len(入口们) != 1:
        return [
            "读取入口应恰好一份："
            + "、".join(p.relative_to(PROJECT_ROOT).as_posix() for p in 入口们)
        ]
    入口 = 入口们[0]
    try:
        规则 = json.loads(入口.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{入口.relative_to(PROJECT_ROOT).as_posix()} 读不出来：{exc}"]
    扫描 = [str(x) for x in 规则.get("扫描目录") or []]
    路由 = 入口.relative_to(DATA).as_posix()
    顶层 = {p.name for p in DATA.iterdir() if p.is_dir()}
    首段 = {项.split("/")[0] for 项 in 扫描}
    if 顶层 != 首段:
        problems.append(f"顶层目录与扫描目录首段不一致：{sorted(顶层 ^ 首段)}")

    登记 = set(扫描)
    for 项 in 扫描:
        段 = 项.split("/")
        清单 = DATA / 项 / "组件.json"
        if not 清单.is_file():
            problems.append(f"{项}/ 没有组件清单")
            continue
        if len(段) > 1 and 段[0] == 段[-1]:
            problems.append(f"{项}/ 多了一层：组件名与大类同名时应直接住在大类目录下")
        try:
            数据 = json.loads(清单.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{项}/组件.json 读不出来：{exc}")
            continue
        if str(数据.get("组件")) != 段[-1]:
            problems.append(
                f"{项}/组件.json 的组件名是 {数据.get('组件')}，与目录名 {段[-1]} 不符"
            )
        for 行 in 数据.get("读取规则") or []:
            路径 = str(行.get("路径") or "")
            路径段 = pathlib.PurePosixPath(路径).parts
            if 路径 == 路由:
                # 读取入口本身就在组件根上，没有四类面那一段。
                continue
            if not 路径.startswith(项 + "/"):
                problems.append(f"{项}/组件.json 注册了别处的文件：{路径}")
                continue
            if len(路径段) < len(段) + 2 or 路径段[len(段)] not in 四类面:
                problems.append(f"{项}/组件.json 的路径没有组件内语义分类：{路径}")

    for 大类 in sorted(顶层):
        目录 = DATA / 大类
        if not (目录 / "说明.md").is_file():
            problems.append(f"{大类}/ 缺说明.md")
        for 子 in sorted(p for p in 目录.iterdir() if p.is_dir()):
            名字 = f"{大类}/{子.name}"
            if 子.name in 四类面 or 名字 in 登记:
                continue
            problems.append(f"{名字}/ 既不是四类面，也不在扫描目录里")
    return problems


def _数据词表() -> set[str]:
    """`data/` 里出现过的全部键名与字符串取值。**反引号里只许出现这里有的东西**。

    这条用来把「数据」和「代码」分开：`有效秒数`、`结算秒数`、`xy`、`send` 都是数据里真有的
    键或取值，而 `request_id`、`plan_equip`、`StateConflictError` 是代码里的名字。说明是逻辑
    的事实源，不该被实现的名字绑住（第 84 轮负责人口径：说明里不用把代码标出来）。
    """

    词: set[str] = set()

    def 走(节点: object) -> None:
        if isinstance(节点, dict):
            for 键, 值 in 节点.items():  # type: ignore[union-attr]
                词.add(str(键))
                走(值)
        elif isinstance(节点, list):
            for 项 in 节点:  # type: ignore[union-attr]
                走(项)
        elif isinstance(节点, str):
            词.add(节点)

    for path in DATA.rglob("*.json"):
        if path.name == "组件.json":
            continue
        try:
            走(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
    return 词


#: 说明的功能一节里，反引号中允许出现的英文词形（其余英文一律算代码标识符）。
英文词形 = re.compile(r"^[A-Za-z_][A-Za-z0-9_.()\[\]:<>|, ]*$")


def _是数据路径(名字: str) -> bool:
    """`规则/切磋.json`、`data/战斗/规则/五行.json`、`战斗/定义/属性.json` 都算数据路径。

    判据是「它真的指向一个数据文件」，而不是看它长什么样——这样组件内相对路径与跨组件的
    `data/…` 前缀两种写法都放行，只要文件真在。
    """

    if not 名字.endswith((".json", ".md")):
        return False
    if 名字.startswith(("game/", "tools/", "tests/", "launch/", "message/")):
        return False
    去掉前缀 = 名字[len("data/"):] if 名字.startswith("data/") else 名字
    if "*" in 去掉前缀:
        return bool(list(DATA.glob(去掉前缀)))
    return (DATA / 去掉前缀).exists()


def check_component_function_docs() -> list[str]:
    """每个组件的 `说明.md` 必须有一节 `## 功能`，写成**中文逻辑**，且不夹带代码。

    负责人口径（第 79、84 轮）：**每个二级组件的说明里要把功能按点分类写清楚**，便于逐条审改；
    说明是逻辑的事实源——负责人改中文描述，实现照着改。因此说明里**不写代码**：不出现
    `game/...`、不出现 `.py`、不出现函数名/类名/异常名/变量名，反引号只留给数据键与数据取值
    （数据里真有的英文键如 `xy` 可以，代码里的 `request_id` 不行）。本包读过哪些文件由文末的
    `## 数据集` 表统一交代，那张表里的路径逐条验存在。

    这条同时挡住几种退化：新组件没写功能一节；条目编号断号；功能一节把**页面文案与按钮动作**
    又抄了一遍（那是 `展示/` 的唯一出处）；说明被实现的名字绑住（改实现就得跟着改说明）。
    """

    problems: list[str] = []
    词表 = _数据词表()
    反引号 = re.compile(r"`([^`\s]+)`")
    for 清单 in sorted(DATA.rglob("组件.json")):
        组件目录 = 清单.parent
        相对 = 组件目录.relative_to(DATA).as_posix()
        说明 = 组件目录 / "说明.md"
        if not 说明.is_file():
            problems.append(f"{相对}/ 缺说明.md")
            continue
        文本 = 说明.read_text(encoding="utf-8")
        if "## 功能" not in 文本:
            problems.append(f"{相对}/说明.md 缺「## 功能」一节")
            continue
        片段 = 文本.split("## 功能", 1)[1].split("\n## ", 1)[0]
        if not re.search(r"^### ", 片段, flags=re.M):
            problems.append(f"{相对}/说明.md 的功能一节没有分类（缺 `### `）")
        编号 = [int(x) for x in re.findall(r"^(\d+)\. ", 片段, flags=re.M)]
        if not 编号:
            problems.append(f"{相对}/说明.md 的功能一节没有编号条目")
        elif 编号 != list(range(1, len(编号) + 1)):
            problems.append(
                f"{相对}/说明.md 的功能条目编号不是 1..{len(编号)} 连续（{'、'.join(map(str, 编号[:8]))}…）"
            )
        for 名字 in 反引号.findall(片段):
            if 词表 and 名字 in 词表:
                continue
            if 名字.startswith(("http", "data/")) or 名字 in {"组件.json"}:
                continue
            # 数据文件路径留在说明里是好事（`规则/切磋.json`、`data/战斗/规则/五行.json`）：
            # 改数据的人要照着找。只有指向代码的才算夹带。
            if _是数据路径(名字):
                continue
            if pathlib.PurePosixPath(名字).parts[0] in 四类面:
                continue
            if 名字.endswith(".md"):
                continue
            if 英文词形.match(名字) or "/" in 名字 or 名字.endswith(".py"):
                problems.append(
                    f"{相对}/说明.md 的功能一节夹带了代码：`{名字}`（说明只写中文逻辑，"
                    f"反引号只留给数据键、数据取值与数据文件）"
                )
        # 页面文案与按钮动作的唯一出处是 `展示/`，说明里不再抄一遍。**只拦这一层**：
        # `展示/` 底下被代码读取与校验的数据（如 `展示/行程.json` 的叙事模板）算逻辑，允许引用。
        for 面文件 in ("展示/文本.json", "展示/按钮.json", "展示/按钮/", "展示/分页.json"):
            if f"`{面文件}" in 片段:
                problems.append(
                    f"{相对}/说明.md 的功能一节写了展示文案或按钮（{面文件}）："
                    "页面与动作以 `展示/` 目录为准，说明只讲逻辑"
                )
        problems.extend(_数据集表问题(文本, 组件目录, 相对))
    return problems


def _数据集表问题(文本: str, 组件目录: pathlib.Path, 相对: str) -> list[str]:
    """说明末尾的 `## 数据集` 表要把本包读的每个文件都列上，且路径真的存在。"""

    if "## 数据集" not in 文本:
        return [f"{相对}/说明.md 缺「## 数据集」表（本包读过哪些文件由它统一交代）"]
    片段 = 文本.split("## 数据集", 1)[1].split("\n## ", 1)[0]
    问题: list[str] = []
    行s = [
        行 for 行 in 片段.splitlines()
        if 行.startswith("|") and not _MD分隔行.match(行) and "数据集" not in 行
    ]
    if not 行s:
        return [f"{相对}/说明.md 的数据集表没有数据行"]
    for 行 in 行s:
        格 = [x.strip() for x in 行.strip("|").split("|")]
        if len(格) < 2:
            问题.append(f"{相对}/说明.md 的数据集表列数不对：{行[:40]}")
            continue
        路径 = 格[1].strip("`")
        if not 路径:
            continue
        if pathlib.PurePosixPath(路径).parts[0] not in 四类面:
            continue  # 只验「从四类面开始」的组件内相对路径
        候选 = 组件目录 / 路径
        if not _引用存在(候选):
            问题.append(f"{相对}/说明.md 的数据集表指向不存在的文件：{路径}")
    return 问题


def _引用存在(候选: pathlib.Path) -> bool:
    """路径存在性（含通配符）。通配符可能出现在中间几段，所以整条相对路径一次 glob。"""

    相对 = 候选.relative_to(PROJECT_ROOT).as_posix()
    if "*" in 相对:
        return bool(list(PROJECT_ROOT.glob(相对)))
    return 候选.exists()


#: Markdown 结构检查用到的行型（对齐仓库根的 `.markdownlint.json`）。
_MD标题 = re.compile(r"^(#{1,6})\s+(\S.*)$")
_MD围栏 = re.compile(r"^(`{3,}|~{3,})\s*(\S*)\s*$")
_MD有序 = re.compile(r"^(\s*)(\d+)\.\s")
_MD无序 = re.compile(r"^(\s*)([-*+])\s")
_MD表格 = re.compile(r"^\s*\|")
_MD分隔行 = re.compile(r"^\s*\|[\s:|-]+\|\s*$")


def _markdown问题(文本: str) -> list[str]:
    """一份 Markdown 的结构体检（与 `.markdownlint.json` 同一套规则，行长不管）。"""

    行s = 文本.splitlines()
    问题: list[str] = []
    if not 行s:
        return ["空文件"]
    # 一级标题只在**代码块外**数：代码块里的 `#` 是注释，不是标题。
    在外 = True
    一级 = 0
    for 行 in 行s:
        if _MD围栏.match(行):
            在外 = not 在外
            continue
        if 在外 and 行.startswith("# "):
            一级 += 1
    if 一级 != 1:
        问题.append(f"一级标题必须恰好一个（现在 {一级} 个）")
    头 = _MD标题.match(行s[0]) if 行s else None
    if 头 is None or len(头.group(1)) != 1:
        问题.append("第 1 行必须是一级标题")
    if not 文本.endswith("\n"):
        问题.append("文件末尾要有换行")
    if 文本.endswith("\n\n"):
        问题.append("文件末尾多空行")
    上级别 = 1
    在围栏 = False
    空行数 = 0
    段落 = ""
    列数 = 0
    for i, 行 in enumerate(行s, 1):
        if 行.rstrip() != 行:
            问题.append(f"{i}: 行尾空白")
        if "\t" in 行:
            问题.append(f"{i}: 制表符")
        栏 = _MD围栏.match(行)
        if 栏:
            空行数 = 0
            if not 在围栏:
                在围栏 = True
                if not 栏.group(2):
                    问题.append(f"{i}: 代码块没写语言")
                if i > 1 and 行s[i - 2].strip():
                    问题.append(f"{i}: 代码块前没有空行")
            else:
                在围栏 = False
                if i < len(行s) and 行s[i].strip():
                    问题.append(f"{i}: 代码块后没有空行")
            continue
        if 在围栏:
            continue
        if not 行.strip():
            空行数 += 1
            if 空行数 > 1 and i < len(行s):
                问题.append(f"{i}: 连续空行")
            段落 = ""  # 空行终结列表与表格
            continue
        空行数 = 0
        标题 = _MD标题.match(行)
        if 标题:
            级别 = len(标题.group(1))
            if 级别 > 上级别 + 1:
                问题.append(f"{i}: 标题级别从 {上级别} 跳到 {级别}")
            上级别 = 级别
            if i > 1 and 行s[i - 2].strip():
                问题.append(f"{i}: 标题前没有空行")
            if i < len(行s) and 行s[i].strip():
                问题.append(f"{i}: 标题后没有空行")
            if 标题.group(2).rstrip().endswith(("。", "：", "，")):
                问题.append(f"{i}: 标题以标点结尾")
            段落 = "标题"
            continue
        if _MD有序.match(行) or _MD无序.match(行):
            if 段落 != "列表" and i > 1 and 行s[i - 2].strip():
                问题.append(f"{i}: 列表前没有空行")
            段落 = "列表"
            continue
        if _MD表格.match(行):
            if 段落 != "表格":
                if i > 1 and 行s[i - 2].strip():
                    问题.append(f"{i}: 表格前没有空行")
                列数 = 行.count("|")
                if i < len(行s) and not _MD分隔行.match(行s[i]):
                    问题.append(f"{i}: 表格缺少分隔行")
            elif 行.count("|") != 列数:
                问题.append(f"{i}: 表格列数与表头不符（{行.count('|')} vs {列数}）")
            段落 = "表格"
            continue
        if 段落 == "列表" and 行[:1] in {" ", "\t"}:
            continue  # 折行续写，仍算同一个列表
        if 段落 in {"列表", "表格"} and i > 1 and 行s[i - 2].strip():
            问题.append(f"{i}: {段落}后没有空行")
        段落 = "段落"
    if 在围栏:
        问题.append("代码块没有闭合")
    return 问题


def check_component_markdown() -> list[str]:
    """每个二级组件的 `说明.md` 与 `data/说明.md` 要过 Markdown 结构检查。

    负责人口径（第 84 轮）：**说明的 md 格式不要有警告**。规则与仓库根的
    `.markdownlint.json` 一致（只关掉行长限制）：一级标题唯一且在首行、标题级别不跳级、
    标题/列表/表格/代码块前后留空行、代码块写语言并闭合、表格列数对齐、无连续空行与行尾
    空白、文件以单个换行结尾。**再加一条正文本身的检查**：说明里的 Markdown 链接必须指向
    真实存在的文件（坏链是说明与数据脱节的另一种形态）。
    """

    问题: list[str] = []
    目标 = [p.parent / "说明.md" for p in sorted(DATA.rglob("组件.json"))]
    目标.append(DATA / "说明.md")
    链接 = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
    for 说明 in 目标:
        if not 说明.is_file():
            continue
        相对 = 说明.relative_to(PROJECT_ROOT).as_posix()
        文本 = 说明.read_text(encoding="utf-8")
        for 一条 in _markdown问题(文本):
            问题.append(f"{相对} 的 Markdown：{一条}")
        for 目标路径 in 链接.findall(文本):
            if 目标路径.startswith(("http", "#")):
                continue
            去锚 = 目标路径.split("#")[0]
            if 去锚 and not (说明.parent / 去锚).exists():
                问题.append(f"{相对} 的链接指向不存在的文件：{目标路径}")
    return 问题


def check_rule_keys_described() -> list[str]:
    """代码读的每个规则键，都要在所属组件的 `说明.md` 里写到。

    「通过说明控制代码」的前提是**说明覆盖全部可调的行为**：数据键是代码真正读的参数，
    某个键有人读、说明里却一个字没提，负责人就没法靠改说明来控制它。这条与
    `check_unread_rule_keys` 正好互为反向——那边管「数据里没人读的声明删掉」，这边管
    「代码读了的行为说明里必须有」。

    范围与例外：只看 `规则/` 面（`定义/` 是按表遍历的词表，`内容/` 是实体）；
    `展示/` 面除外（页面文案与按钮是展示契约，说明按约定不重复）；读取器与展示层的通用键
    （`说明`/`名称`/`编号`…）不必逐条写。
    """

    运行时 = "\n".join(
        path.read_text(encoding="utf-8")
        for 根 in ("game", "launch", "message")
        for path in (PROJECT_ROOT / 根).rglob("*.py")
        if "__pycache__" not in path.parts
    )
    被读 = set(re.findall(r'get\("([^"\n]{1,24})"\)', 运行时))
    被读 |= set(re.findall(r'\["([^"\n]{1,24})"\]', 运行时))
    被读 |= set(re.findall(r"get\('([^'\n]{1,24})'\)", 运行时))
    说明文 = {
        清单.parent: (清单.parent / "说明.md").read_text(encoding="utf-8")
        for 清单 in DATA.rglob("组件.json")
    }

    problems: list[str] = []
    for path in sorted(DATA.rglob("*.json")):
        if path.name == "组件.json":
            continue
        段 = path.relative_to(DATA).parts
        if "展示" in 段:
            continue
        if not (("规则" in 段[1:-1]) or (len(段) >= 3 and 段[1] == "规则")):
            continue
        组件 = DATA
        for 上 in path.parents:
            if (上 / "组件.json").is_file():
                组件 = 上
                break
        说 = 说明文.get(组件, "")
        缺: set[str] = set()

        def 走(节点: object, 前缀: str = "") -> None:
            if isinstance(节点, dict):
                for 键, 值 in 节点.items():  # type: ignore[union-attr]
                    名 = str(键)
                    走(值, f"{前缀}{名}.")
                    if 名 in COMMON_KEYS or len(名) < 2 or 名 not in 被读 or 名 in 说:
                        continue
                    缺.add(f"{前缀}{名}")
            elif isinstance(节点, list):
                for 项 in 节点:  # type: ignore[union-attr]
                    走(项, 前缀)

        走(json.loads(path.read_text(encoding="utf-8")))
        if 缺:
            problems.append(
                f"{组件.relative_to(DATA).as_posix()}/说明.md 没写到这些在读的规则键："
                f"{'、'.join(f'`{x}`' for x in sorted(缺)[:8])}"
                f"{'…' if len(缺) > 8 else ''}（说明是行为的唯一出处，读得到的键就要写得下）"
            )
    return problems


#: 数据目录里**唯一允许引代码**的一份：这份总约定本身要举例。
引代码豁免 = {pathlib.PurePosixPath("说明.md")}

#: 写法上像标识符、其实是数据一侧的东西：JSON 字面量、坐标符号、目录名。
数据侧符号 = frozenset({"true", "false", "null", "x", "y", "z", "xy", "H", "data", "tools"})


def check_data_docs_no_code() -> list[str]:
    """`data/` 下的说明一律不引代码（组件说明、领域说明、内容说明都是）。

    负责人口径（第 84 轮）：**说明是逻辑的事实源，不是实现的注解**。负责人只改说明里的中文
    逻辑，实现照着说明改；说明里写满 `game/...` 与函数名，改实现时就跟着过期。允许保留的是
    **数据**（数据键、取值、数据文件路径）与**操作指引**（`tools/…` 这种「改完跑这支脚本验」
    的指针）。唯一豁免 `data/说明.md`——它是这套约定本身，要举例。
    """

    词表 = _数据词表()
    problems: list[str] = []
    for path in sorted(DATA.rglob("*.md")):
        相对 = path.relative_to(DATA).as_posix()
        if pathlib.PurePosixPath(相对) in 引代码豁免:
            continue
        文本 = path.read_text(encoding="utf-8")
        if "game/" in 文本:
            problems.append(
                f"data/{相对} 引了实现路径（`game/…`）：说明写中文逻辑，实现路径不进说明"
            )
        for 名字 in re.findall(r"`([^`\s]+)`", 文本):
            if 名字 in 词表 or 名字 in 数据侧符号:
                continue
            if 名字.startswith(("http", "data/", "tools/", "launch/", "message/")):
                continue
            if pathlib.PurePosixPath(名字).parts[0] in 四类面 or 名字.endswith(".md"):
                continue
            if _是数据路径(名字):
                continue
            if 英文词形.match(名字) or 名字.endswith(".py"):
                problems.append(
                    f"data/{相对} 引了代码标识符：`{名字}`（说明只写中文逻辑，"
                    f"反引号留给数据键、取值与数据路径）"
                )
    return problems


def check_contract_placement() -> list[str]:
    """字段契约必须住在 `定义/` 或 `规则/`，不得混进 `内容/` 与 `展示/`。

    `data/说明.md`：定义登记概念，规则保存裁定参数，内容保存实体和资源池，展示保存
    文本及界面契约。字段契约是裁定参数。**原先先天灵宝与阵法各把它放在 `内容/` 里**
    ——那还是唯一一处「内容目录里躺着的不是实体」的地方（第 76 轮挪进 `规则/`）。

    判据认两种形态：文件名以 `字段契约.json` 结尾，或正文里带 `必填字段` / `可选字段`
    （`物品/基础物品/规则/分类.json` 就是后一种）。
    """

    problems: list[str] = []
    for path in sorted(DATA.rglob("*.json")):
        if path.name == "组件.json":
            continue
        parts = path.relative_to(DATA).parts
        if len(parts) < 3 or parts[1] not in {"内容", "展示"}:
            continue
        if path.name.endswith("字段契约.json"):
            problems.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}：契约按文件名判定")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if '"必填字段"' in text or '"可选字段"' in text:
            problems.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}：正文带字段契约")
    return problems


#: 读取器与展示层按约定读的通用键，不要求逐处出现字面量。
COMMON_KEYS = frozenset({
    "说明", "名称", "编号", "组件", "读取规则", "路径", "结构", "数据集", "实体类别",
    "编号类别", "池", "字段", "类型", "类别", "必填", "可选", "默认", "选项", "权重",
    "顺序", "排序", "标签", "备注", "资源池字段", "扫描目录", "分组", "标题", "文本",
    "条件", "效果", "范围", "对象", "数值", "描述", "启用", "颜色", "图标", "分页",
    "按钮", "动作", "命令", "参数", "提示", "值", "键", "内容",
})


#: 展示面板与分区的名字：挂在文案树上当容器，展示层按约定取整节，本身不是文案。
DISPLAY_SECTION_KEYS = frozenset({
    "图标", "分页", "格式", "页面", "位置", "行为", "样式", "提交", "查看", "结果", "错误",
    "状态", "标识", "编号列", "每页数量", "标题", "副标题", "提示", "颜色", "分组", "列表",
    "进度", "发起", "命令", "文本", "按钮", "条件",
})


def _rule_files() -> list[pathlib.Path]:
    """要判「有没有人读」的数据文件：`规则` 面，加上展示面的 `文本.json`。

    `规则` 那一层可能在大类目录下（`宗门/规则/…`），也可能在组件目录下
    （`玩法/队伍/规则/…`、`物品/炼丹/规则/…`）。**`展示/规则/` 不是规则面**——那是
    展示层按节/键取的叙事模板与措辞表，按文案判（它也是 `文本.json`）。
    展示面的按钮与分页不判：投影器按约定整份读它们的结构。
    """

    目标: list[pathlib.Path] = []
    for path in sorted(DATA.rglob("*.json")):
        if path.name == "组件.json":
            continue
        段 = path.relative_to(DATA).parts
        是规则 = len(段) >= 3 and "规则" in 段[1:-1] and "展示" not in 段[1:-1]
        是文案 = path.name == "文本.json" and "展示" in 段
        if 是规则 or 是文案:
            目标.append(path)
    return 目标


def _all_keys(node: object, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """列出文档里所有键的路径（含嵌套），用于逐键判「有没有人读」。"""

    路径: list[tuple[str, ...]] = []
    if isinstance(node, dict):
        for 键, 值 in node.items():
            路径.append(prefix + (str(键),))
            路径.extend(_all_keys(值, prefix + (str(键),)))
    elif isinstance(node, list):
        for 项 in node:
            路径.extend(_all_keys(项, prefix))
    return 路径


def _dynamic_key_patterns() -> list[re.Pattern[str]]:
    """把源码里含占位符的 f-string 变成正则：匹配得上的键可能是被拼出来读的。

    `growth/service.py` 就是 `late.get(f"{prefix}系数")` —— 静态看 `中段系数` 不在
    任何字面量里，实际却真的被读。模板让它留在数据里，宁可漏删不可误删。
    """

    模板: list[re.Pattern[str]] = []
    for 根 in ("game", "launch", "message"):
        目录 = PROJECT_ROOT / 根
        if not 目录.is_dir():
            continue
        for path in sorted(目录.rglob("*.py")):
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.JoinedStr):
                    continue
                文 = ""
                for 段 in node.values:
                    if isinstance(段, ast.Constant) and isinstance(段.value, str):
                        文 += 段.value
                    else:
                        文 += "\x00"
                if "\x00" in 文 and len(文.replace("\x00", "")) >= 1:
                    模板.append(re.compile("^" + re.escape(文).replace("\x00", ".*") + "$"))
    return 模板


def check_unread_rule_keys(source: str) -> list[str]:
    """规则文件里不得留下没人读的键（第 83 轮负责人口径：没用的规则删掉）。

    一条规则只有在**有人读**的时候才算规则。没人读的键既不约束代码，也看不出代码到底
    按什么裁定——它是「声明了却没人执行」的谎，比没有更坏。

    判据是保守的三条：键名作为字符串字面量出现在 `game`/`launch`/`message`（以及
    `tools`/`tests`——工具与测试也算消费者）里，或者能被源码里的 f-string 拼出来
    （`f"{prefix}系数"`），或者是读取器与展示层的通用键。
    **`定义/` 不判**：属性表是按表遍历的词表，`护盾加成` 在代码里 0 次字面量却被
    16 个数据文件引用，按这条判会误删属性。
    **展示面按文案判**（`展示/**/文本.json`）：展示层按「节 / 键」取文案，没人取的字符串
    玩家永远看不到；分区名与按钮分页按约定整份读，写进 `DISPLAY_SECTION_KEYS`。

    顶层键**全部**没人读的文件会额外点名——那是整份声明没人执行（`灵兽修炼.json`、
    `境界突破.json`、`同行.json`、`炼丹/规则/战丹.json` 都属于这一类）。
    """

    字面量 = set(re.findall(r'"([^"\n]{1,24})"', source)) | set(
        re.findall(r"'([^'\n]{1,24})'", source)
    )
    for 根 in ("launch", "message", "tools", "tests"):
        目录 = PROJECT_ROOT / 根
        if not 目录.is_dir():
            continue
        for path in sorted(目录.rglob("*.py")):
            文 = path.read_text(encoding="utf-8")
            字面量 |= set(re.findall(r'"([^"\n]{1,24})"', 文))
            字面量 |= set(re.findall(r"'([^'\n]{1,24})'", 文))
    模板 = _dynamic_key_patterns()

    def 有读者(名: str, 文案: bool) -> bool:
        if 名 in 字面量 or any(t.match(名) for t in 模板):
            return True
        return 名 in (COMMON_KEYS | DISPLAY_SECTION_KEYS if 文案 else COMMON_KEYS)

    problems: list[str] = []
    for path in _rule_files():
        文档 = json.loads(path.read_text(encoding="utf-8"))
        相对 = path.relative_to(PROJECT_ROOT).as_posix()
        文案 = path.name == "文本.json" and "展示" in path.relative_to(DATA).parts
        顶层 = list(文档) if isinstance(文档, dict) else []
        死键 = [".".join(键) for 键 in _all_keys(文档) if not 有读者(键[-1], 文案)]
        if 顶层 and all(not 有读者(str(名), 文案) for 名 in 顶层):
            problems.append(f"{相对}：整份没人读（顶层键 {len(顶层)} 个全无消费者），确认作废就删掉")
            continue
        if 死键:
            problems.append(
                f"{相对}：{len(死键)} 个键没人读（{'、'.join(sorted(set(死键))[:6])}"
                f"{'…' if len(死键) > 6 else ''}）——接上消费者，或者删掉这条声明"
            )
    return problems


def check_dataset_consumers(source: str) -> list[str]:
    """找出无消费者的非池数据集。

    只有**没有实体类别**的数据集才必须靠 `dataset("名")` 访问，因此可以按名字
    判断有无消费者。带实体类别的数据集由 `entity()` / `entities()` 按实体类别
    消费，名字不出现在源码里是正常的，不在此判定。
    """

    problems: list[str] = []
    for name, info in sorted(_declared().items()):
        if name in POOL_SECTIONS or info["entity"]:
            continue
        if f'"{name}"' not in source and f"'{name}'" not in source:
            components = "、".join(sorted(info["components"]))  # type: ignore[arg-type]
            problems.append(
                f"数据集 {name}（组件：{components}）无实体类别且未被 dataset() 引用"
            )
    return problems


# 池数据集由 `data/基础/读取规则.json` 的 `资源池字段` 声明，资源池服务按池文件名
# 展开，因此名字不出现在业务代码里是正常的，不按"无代码引用"判定。
POOL_SECTIONS = {
    "功法池", "真意池", "气机池", "器律池", "灵植池", "灵矿池",
    "兽宝池", "丹药池", "首领池", "辅助池", "属从池", "奖励池",
}


def report_contract_coverage() -> None:
    """打印字段契约覆盖率与手写校验规模。"""

    with_contract = 0
    total = 0
    for path in DATA.rglob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        total += 1
        text = json.dumps(raw, ensure_ascii=False)
        if '"必填字段"' in text or '"可选字段"' in text or ('"字段"' in text and '"类型"' in text):
            with_contract += 1
    print(f"  数据文件带字段契约: {with_contract}/{total}（{with_contract * 100 // max(total, 1)}%）")

    definitions: Counter[str] = Counter()
    calls = 0
    for path in GAME.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and VALIDATOR_NAME.match(node.name):
                definitions[node.name] += 1
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if VALIDATOR_NAME.match(node.func.id):
                    calls += 1
    print(f"  手写字段校验辅助定义: {sum(definitions.values())} 处，调用点 {calls} 处")
    for name, count in definitions.most_common(5):
        print(f"      {name}: {count} 处重复定义")


def check_terrain_pace() -> list[str]:
    """地形**不再参与输出倍率**，这条判据改为**反向看门**（第 41 轮拆掉的开关）。

    旧契约是「每一档地形都要配到倍率，别让它静默落到无相那一档」——它守的是
    `输出倍率 = 伤害.json.输出倍率 × 地形百分比 / 100` 那层耦合。新契约恰好相反：
    **输出倍率只有 `伤害.json.输出倍率` 一个出处**，地形只描述战场形态。所以现在查：
    ① 任何一条地形都不许再出现 `输出倍率`；② 整个文档不许再有 `无相地势`；
    ③ 地形清单仍要与 `世界/内容/地形分区.json` 对得上（少列 / 多列都报）。
    ① ② 是把那个开关**堵在门外**：谁把它加回来，`tools/全量核对.py` 当场报错。
    """

    import json as _json

    地形路径 = DATA / "战斗" / "规则" / "地形.json"
    分区路径 = DATA / "世界" / "内容" / "地形分区.json"
    if not 地形路径.exists() or not 分区路径.exists():
        return []
    文档 = _json.loads(地形路径.read_text(encoding="utf-8"))
    分区 = _json.loads(分区路径.read_text(encoding="utf-8"))
    problems: list[str] = []
    if "无相地势" in 文档:
        problems.append(
            "战斗/规则/地形.json 不得再声明 `无相地势`：地形不再调节输出倍率"
            "（输出倍率只有 `伤害.json.输出倍率` 一个出处）"
        )
    需要 = {str(条.get("地形") or "") for 条 in 分区 if isinstance(条, dict)}
    行 = 文档.get("地形")
    if not isinstance(行, list) or not 行:
        return ["战斗/规则/地形.json 的 `地形` 必须是非空数组"]
    登记: set[str] = set()
    for 条 in 行:
        if not isinstance(条, dict):
            problems.append("战斗/规则/地形.json 的 `地形` 里混了非对象")
            continue
        名 = str(条.get("地形") or "").strip()
        if not 名:
            problems.append("战斗/规则/地形.json 有一行没写 `地形`")
            continue
        if 名 in 登记:
            problems.append(f"地形重复登记：{名}")
            continue
        if "输出倍率" in 条:
            problems.append(
                f"{名} 又声明了 `输出倍率`：地形不得调节输出倍率，倍率请改 `伤害.json.输出倍率`"
            )
        登记.add(名)
    漏 = sorted(需要 - 登记)
    if 漏:
        problems.append(f"这些地形没登记：{'、'.join(漏)}")
    多余 = sorted(登记 - 需要)
    if 多余:
        problems.append(f"这些地形登记了但地形分区里没有：{'、'.join(多余)}")
    return problems


def main() -> int:
    source = _game_source()
    print("JSON 驱动完整性审查")
    print("  字段契约与校验规模：")
    report_contract_coverage()

    problems = check_dataset_consumers(source)
    住处 = check_contract_placement()
    布局 = check_category_layout()
    功能 = check_component_function_docs()
    死规则 = check_unread_rule_keys(source)
    排版 = check_component_markdown()
    没写 = check_rule_keys_described()
    引代码 = check_data_docs_no_code()
    地形 = check_terrain_pace()
    if 地形:
        print()
        print(f"地形战斗节奏问题 {len(地形)} 处：")
        for item in 地形:
            print(f"  {item}")
        print()
        print("地形不再调节输出倍率：地形.json 里不许出现 `输出倍率` 或 `无相地势`。")
        return 1
    print()
    if 布局:
        print(f"大类布局问题 {len(布局)} 处：")
        for item in 布局:
            print(f"  {item}")
        print()
        print("顶层是大类，组件清单在第二层；组件名与大类同名时不再多一层。")
        return 1
    print("大类布局：扫描目录、组件清单与注册路径对得上")
    if 功能:
        print(f"组件说明问题 {len(功能)} 处：")
        for item in 功能:
            print(f"  {item}")
        print()
        print("说明要按点写中文逻辑：不夹带代码，条目编号连续，数据集表逐条有效。")
        return 1
    print("组件说明：中文逻辑、不夹带代码、数据集表有效")
    if 排版:
        print(f"说明排版问题 {len(排版)} 处：")
        for item in 排版[:20]:
            print(f"  {item}")
        if len(排版) > 20:
            print(f"  …… 另 {len(排版) - 20} 条")
        print()
        print("规则见仓库根的 .markdownlint.json（只关掉行长限制）。")
        return 1
    print("说明排版：标题、列表、表格、代码块都合规")
    if 没写:
        print(f"说明没覆盖到的规则键 {len(没写)} 份：")
        for item in 没写:
            print(f"  {item}")
        print()
        print("代码读得到的键，说明里就要写得下——说明是行为的唯一出处。")
        return 1
    print("代码读的规则键，说明里都写到了")
    if 引代码:
        print(f"说明引了代码 {len(引代码)} 处：")
        for item in 引代码[:20]:
            print(f"  {item}")
        if len(引代码) > 20:
            print(f"  …… 另 {len(引代码) - 20} 条")
        print()
        print("说明写中文逻辑：`game/…`、函数名、类名都删掉，只留数据路径与工具入口。")
        return 1
    print("说明里没有代码引用")
    if 住处:
        print(f"契约住错面 {len(住处)} 处：")
        for item in 住处:
            print(f"  {item}")
        print()
        print("契约是裁定参数，该住 定义/ 或 规则/；内容/ 只放实体与资源池。")
        return 1
    print("字段契约都住在 定义/ 或 规则/")
    if 死规则:
        print(f"没人读的规则或文案 {len(死规则)} 份：")
        for item in 死规则:
            print(f"  {item}")
        print()
        print("一条规则只有在有人读的时候才算规则；没人读的声明接上消费者或者删掉。")
        return 1
    print("规则与展示文案里的键都有消费者")
    if 地形:
        print(f"地形战斗节奏问题 {len(地形)} 处：")
        for item in 地形:
            print(f"  {item}")
        print()
        print("地形不再调节输出倍率：地形.json 里不许出现 `输出倍率` 或 `无相地势`。")
        return 1
    print("地形战斗节奏：地形分区里的每一档都配到了，倍率在区间内")
    if problems:
        print(f"无消费者数据集 {len(problems)} 项：")
        for item in problems:
            print(f"  {item}")
        print()
        print("这类数据会被启动校验通过并进入快照，但改动它不影响游戏。")
        print("处理方式：接上消费者（让校验器读取该契约），或从组件.json 摘除并移走文件。")
        return 1
    print("所有非池数据集都有代码引用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
