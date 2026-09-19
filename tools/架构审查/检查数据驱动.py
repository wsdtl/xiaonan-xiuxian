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


def check_component_function_docs() -> list[str]:
    """每个组件的 `说明.md` 必须有一节 `## 功能`，且它引用的依据文件真的存在。

    负责人口径（第 79 轮）：**每个二级组件的说明里要把功能按点分类写清楚**，便于逐条审查。
    写法见 `data/说明.md`——每条写成「玩家做什么 → 按哪份数据算出什么 → 落到哪里」，
    末尾用反引号标出依据文件（相对组件目录，跨包或代码依据写完整路径）。

    这条同时挡住三种退化：新组件没写功能一节；功能条目引用了**不存在**的规则/内容/代码文件
    （说明与设计脱节）；功能一节把**页面文案与按钮动作**又抄了一遍——那是 `展示/` 目录的
    唯一出处，说明只讲代码逻辑（`展示/` 下被代码读取的数据不算，如 `展示/行程.json`）。
    占位符（`内容/<区域>/<地点>/…`）与通配符按目录展开校验。
    """

    problems: list[str] = []
    引用 = re.compile(r"`([^`\s]+)`")
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
        if not re.search(r"^\d+\. ", 片段, flags=re.M):
            problems.append(f"{相对}/说明.md 的功能一节没有编号条目")
        for 名字 in 引用.findall(片段):
            if "<" in 名字 or ">" in 名字 or "…" in 名字 or 名字.startswith(("game/", "http")):
                continue
            if 名字.startswith("data/"):
                候选 = PROJECT_ROOT / 名字
            elif 名字.startswith(tuple(f"{名}/" for 名 in 四类面)):
                候选 = 组件目录 / 名字
            else:
                continue
            if not _引用存在(候选):
                problems.append(f"{相对}/说明.md 的功能依据不存在：{名字}")
        # 页面文案与按钮动作的唯一出处是 `展示/`，说明里不再抄一遍。**只拦这一层**：
        # `展示/` 底下别的文件（如 `展示/行程.json` 的叙事模板、`展示/规则/文本.json` 的
        # 措辞表）如果被代码读取与校验，那是代码逻辑的一部分，允许引用。
        for 面文件 in ("展示/文本.json", "展示/按钮.json", "展示/按钮/", "展示/分页.json"):
            if f"`{面文件}" in 片段:
                problems.append(
                    f"{相对}/说明.md 的功能一节写了展示文案或按钮（{面文件}）："
                    "页面与动作以 `展示/` 目录为准，说明只讲代码逻辑"
                )
        if "`game/" not in 片段:
            problems.append(
                f"{相对}/说明.md 的功能一节没有引用实现它的代码：这一节讲的是代码逻辑，"
                "依据里至少要有一条 `game/…`"
            )
    return problems


def _引用存在(候选: pathlib.Path) -> bool:
    if "*" in 候选.name:
        return bool(list(候选.parent.glob(候选.name)))
    return 候选.exists()


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


def _rule_files() -> list[pathlib.Path]:
    """`data/` 里四类面中「规则」面下的全部 JSON（定义面是按表遍历的词表，不在判定内）。"""

    目标: list[pathlib.Path] = []
    for path in sorted(DATA.rglob("*.json")):
        if path.name == "组件.json":
            continue
        段 = path.relative_to(DATA).parts
        if len(段) < 3 or 段[1] != "规则":
            continue
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

    判据是保守的三条：键名作为字符串字面量出现在 `game`/`launch`/`message` 里，或者
    能被源码里的 f-string 拼出来（`f"{prefix}系数"`），或者是读取器与展示层的通用键。
    **只判 `规则/` 面**：`定义/` 是按表遍历的词表，`护盾加成` 在代码里 0 次字面量却被
    16 个数据文件引用，按这条判会误删属性。

    顶层键**全部**没人读的文件会额外点名——那是整份声明没人执行（`灵兽修炼.json`、
    `境界突破.json`、`同行.json` 都属于这一类）。
    """

    SKIP = {"__pycache__", ".venv", ".git"}
    _ = SKIP
    字面量 = set(re.findall(r'"([^"\n]{1,24})"', source)) | set(
        re.findall(r"'([^'\n]{1,24})'", source)
    )
    for 根 in ("launch", "message"):
        目录 = PROJECT_ROOT / 根
        if not 目录.is_dir():
            continue
        for path in sorted(目录.rglob("*.py")):
            文 = path.read_text(encoding="utf-8")
            字面量 |= set(re.findall(r'"([^"\n]{1,24})"', 文))
            字面量 |= set(re.findall(r"'([^'\n]{1,24})'", 文))
    模板 = _dynamic_key_patterns()

    def 有读者(名: str) -> bool:
        return 名 in 字面量 or 名 in COMMON_KEYS or any(t.match(名) for t in 模板)

    problems: list[str] = []
    for path in _rule_files():
        文档 = json.loads(path.read_text(encoding="utf-8"))
        相对 = path.relative_to(PROJECT_ROOT).as_posix()
        顶层 = list(文档) if isinstance(文档, dict) else []
        死键 = [".".join(键) for 键 in _all_keys(文档) if not 有读者(键[-1])]
        if 顶层 and all(not 有读者(str(名)) for 名 in 顶层):
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
        print("每个组件的说明.md 要有一节「## 功能」，按点分类，依据文件必须存在。")
        return 1
    print("组件说明：每个组件都有功能一节，依据文件都在")
    if 住处:
        print(f"契约住错面 {len(住处)} 处：")
        for item in 住处:
            print(f"  {item}")
        print()
        print("契约是裁定参数，该住 定义/ 或 规则/；内容/ 只放实体与资源池。")
        return 1
    print("字段契约都住在 定义/ 或 规则/")
    if 死规则:
        print(f"没人读的规则 {len(死规则)} 份：")
        for item in 死规则:
            print(f"  {item}")
        print()
        print("一条规则只有在有人读的时候才算规则；没人读的声明接上消费者或者删掉。")
        return 1
    print("规则文件里的键都有消费者")
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
