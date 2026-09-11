"""四类构筑的形状审查。

功法、真意、气机、器律是四个不同的设计方向，不是同一套模板的四个实例。它们
共用的只有"编号 + 名称 + 说明 + 属性构成"这层身份，其余形状必须各归各的：

```text
功法 40  -> 主动技能（必有一项）+ 被动技能，承载完整战斗循环
真意 41  -> 只有被动技能，一道真意恰好一项
气机 42  -> 只有固定属性加成，不引用事件、不监听、不生成技能
器律 70  -> 只有被动技能 + 器阶 / 铸法 / 兽引，锻在本命武器孔位上
```

启动契约（`game/core/combat/builds.py` + `data/战斗/规则/构筑契约.json`）负责挡住
结构性越界。本脚本负责启动契约不挡、但属于数据缺陷的两类问题：

1. **被动槽位里的非监听效果**：`被动技能.效果[]` 里根不是 `监听事件` 的节点。
   战斗核心只登记监听节点，这些效果从未生效过。
2. **跨类别形状漂移**：例如真意长出主动技能、气机长出事件监听、器律丢掉器阶。

用法：

```powershell
.venv/Scripts/python.exe -X utf8 tools/架构审查/检查构筑形状.py
```

退出码 0 表示没有发现缺陷；1 表示存在未生效效果或形状漂移。
"""

from __future__ import annotations

import json
import pathlib
import sys
from collections import defaultdict

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DATA = PROJECT_ROOT / "data"
SOURCES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("器律", "炼器/内容/器律-*.json"),
)
FORBIDDEN = {
    "气机": ("监听事件",),
    "真意": ("监听事件", "主动技能"),
    "器律": ("监听事件", "主动技能"),
}


def _cards(section: str, pattern: str):
    for path in sorted(DATA.glob(pattern)):
        document = json.loads(path.read_text(encoding="utf-8"))
        for entry in document if isinstance(document, list) else [document]:
            yield path, entry


def _walk(node, path: str):
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")


def check_inactive_passives() -> list[str]:
    """被动槽位里根不是监听事件的效果，战斗核心从来不会登记它们。"""

    problems: list[str] = []
    for section, pattern in SOURCES:
        for path, entry in _cards(section, pattern):
            for index, node in enumerate(entry.get("能力") or ()):
                if node.get("能力") != "被动技能":
                    continue
                for effect_index, effect in enumerate(node.get("效果") or ()):
                    if not isinstance(effect, dict):
                        continue
                    if effect.get("能力") == "监听事件":
                        continue
                    where = f"{entry['编号']}.能力[{index}].效果[{effect_index}]"
                    problems.append(
                        f"{section} {entry['名称']}（{where}）不是监听节点，"
                        f"根能力为 {effect.get('能力') or '<空>'}"
                    )
    return problems


def check_shape_drift() -> list[str]:
    """各方向只允许出现自己的能力；跨方向借用一律报出来。"""

    problems: list[str] = []
    for section, pattern in SOURCES:
        forbidden = FORBIDDEN.get(section, ())
        for path, entry in _cards(section, pattern):
            abilities = entry.get("能力") or ()
            for index, node in enumerate(abilities):
                root = str(node.get("能力") or "")
                if root in forbidden:
                    problems.append(
                        f"{section} {entry['名称']}（能力[{index}]）出现 {root}，"
                        f"不属于{section}的设计方向"
                    )
            if section == "气机":
                for path_name, node in _walk(abilities, f"{entry['编号']}.能力"):
                    if node.get("事件"):
                        problems.append(
                            f"气机 {entry['名称']} 携带事件字段 {node['事件']}："
                            "气机不监听事件"
                        )
                        break
    return problems


def check_weight_uniqueness() -> list[str]:
    """功法、真意、气机同用一张权重表，器律按器阶取值不参与。"""

    owners: dict[int, str] = {}
    problems: list[str] = []
    for section, pattern in SOURCES:
        if section == "器律":
            continue
        for _, entry in _cards(section, pattern):
            weight = entry.get("权重")
            if not isinstance(weight, int) or isinstance(weight, bool):
                problems.append(f"{section} {entry.get('编号')} 缺少正整数权重")
                continue
            previous = owners.get(weight)
            if previous is not None:
                problems.append(f"权重 {weight} 同时属于 {previous} 与 {section} {entry['编号']}")
            else:
                owners[weight] = f"{section} {entry['编号']}"
    return problems


def check_listener_carriers() -> list[str]:
    """战丹和长期伤势也寄存监听节点，同样只允许 `监听事件`。"""

    problems: list[str] = []
    pills = DATA / "炼丹/内容/丹药/战丹"
    for path in sorted(pills.glob("*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            effect = entry.get("使用效果") or {}
            if "战斗机制" in effect:
                problems.append(f"战丹 {entry['编号']} 仍在引用编号机制")
            for index, node in enumerate(effect.get("监听") or ()):
                if node.get("能力") != "监听事件":
                    problems.append(
                        f"战丹 {entry['名称']}（监听[{index}]）不是监听事件，"
                        f"根能力为 {node.get('能力') or '<空>'}"
                    )
    injuries = DATA / "角色/内容/伤势.json"
    for entry in json.loads(injuries.read_text(encoding="utf-8")):
        raw = entry.get("战斗状态") or {}
        if "机制" in raw:
            problems.append(f"长期伤势 {entry['编号']} 仍在引用编号机制")
        for index, node in enumerate(raw.get("监听") or ()):
            if node.get("能力") != "监听事件":
                problems.append(
                    f"长期伤势 {entry['名称']}（监听[{index}]）不是监听事件，"
                    f"根能力为 {node.get('能力') or '<空>'}"
                )
    return problems


def main() -> int:
    print("四类构筑形状审查")
    counts: dict[str, int] = defaultdict(int)
    for section, pattern in SOURCES:
        counts[section] = sum(1 for _ in _cards(section, pattern))
    print("  实体数：" + "、".join(f"{k} {v}" for k, v in counts.items()))

    groups = (
        ("被动槽位里从未生效的效果", check_inactive_passives()),
        ("跨方向形状漂移", check_shape_drift()),
        ("权重冲突", check_weight_uniqueness()),
        ("战丹与长期伤势的监听节点", check_listener_carriers()),
    )
    total = sum(len(items) for _, items in groups)
    print()
    for title, items in groups:
        if not items:
            print(f"{title}: 无")
            continue
        print(f"{title} {len(items)} 项：")
        for item in items:
            print(f"  - {item}")
    print()
    if total:
        print("处理方式：把效果补上正确的监听事件，或从该方向摘除并移到归属方向。")
        return 1
    print("四类构筑形状干净")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
