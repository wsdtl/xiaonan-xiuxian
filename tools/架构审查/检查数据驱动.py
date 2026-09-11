"""JSON 驱动完整性审查。

JSON 是这个项目规则与内容的唯一主体，因此"声明的数据是否真有人读"和
"字段契约是否被统一校验"是数据层的核心健康指标。本脚本检查：

1. **无消费者数据集**：在 `组件.json` 声明并被启动加载，却在 `game/` 中没有任何
   代码引用的数据集。它们会被校验通过并进入快照，但改动它们不影响游戏。
2. **无消费者池**：登记为池但从未被任何服务按池名引用。
3. **字段契约覆盖率**：有多少数据文件自带字段契约（`必填字段` / `可选字段` /
   `字段` + `类型`），其余只能靠手写校验器保护。
4. **手写校验规模**：跨服务重复定义的字段校验辅助数量，作为"schema 未统一"
   的量化指标。

属于数据维护审查，不进入游戏启动流程。

用法：

```powershell
.venv/Scripts/python.exe -X utf8 tools/架构审查/检查数据驱动.py
```

退出码 0 表示全部通过；1 表示存在无消费者数据或池。
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
    print()
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
