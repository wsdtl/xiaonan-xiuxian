"""一次性合并重复的原子能力（只做这一件事）。

实测的三对重复：

| 对 | 差异 | 处置 |
| --- | --- | --- |
| `延长状态` / `缩短状态` | 执行器同一个，**只差 `方式` 默认值**（增加/减少） | 并为 `修改状态持续`，`方式` 显式写出 |
| `增加状态层数` / `消耗状态层数` | 同一执行器；消耗多 `方式`、`不足时是否失败` | 并为 `修改状态层数`，`方式` 显式写出 |
| `复制状态` / `转移状态` | **代码语义不同**（保留与否、有无事件、影响几个目标） | **不并**，只改名（另做） |

合并**不改执行器**：`_ability_modify_status_stacks` 与 `_ability_modify_status_duration`
本来就按 `方式` 分支。所以这是一次纯数据改写。

关键保真点：`增加状态层数` 原本**没有** `方式` 与 `不足时是否失败` 两个键，
而执行器对它们的默认是「增加」与 `True`。改写后必须把这两个键**显式补上**，
否则合并后的 schema（`方式` 必填）会挡下这些节点，或者语义漂移。

用法：

```powershell
.venv/Scripts/python.exe -X utf8 tools/一次性迁移/合并原子能力.py            # 试运行
.venv/Scripts/python.exe -X utf8 tools/一次性迁移/合并原子能力.py --落盘
```
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

ABILITY = "能力"

#: 旧名 -> (新名, 键重命名, 需要补齐的 (键, 默认值))
MERGES: dict[str, tuple[str, dict[str, str], tuple[tuple[str, object], ...]]] = {
    "增加状态层数": ("修改状态层数", {}, (("方式", "增加"), ("不足时是否失败", True))),
    "消耗状态层数": ("修改状态层数", {}, (("方式", "减少"),)),
    "延长状态": ("修改状态持续", {"持续数值": "数值"}, (("方式", "增加"),)),
    "缩短状态": ("修改状态持续", {"持续数值": "数值"}, (("方式", "减少"),)),
}


def merge_tree(node: object, counter: dict[str, int]) -> None:
    """递归改写整棵树里的能力节点（保持键序），可就地用于任何 JSON 形状的树。"""

    if isinstance(node, dict):
        name = node.get(ABILITY)
        if isinstance(name, str) and name in MERGES:
            new_name, renames, defaults = MERGES[name]
            after_ability = [item for item in defaults if item[0] == "方式"]
            at_end = [item for item in defaults if item[0] != "方式"]
            rebuilt: dict[str, object] = {}
            for key, value in node.items():
                if key == ABILITY:
                    rebuilt[key] = new_name
                    # `方式` 紧跟 `能力`：与合并前消耗/缩短那批的键序一致，
                    # 也让「方向」这个最关键的开关读起来最靠前。
                    rebuilt.update({k: v for k, v in after_ability if k not in node})
                    continue
                rebuilt[renames.get(key, key)] = value
            rebuilt.update({k: v for k, v in at_end if k not in node})
            node.clear()
            node.update(rebuilt)
            counter[name] += 1
        for value in node.values():
            merge_tree(value, counter)
    elif isinstance(node, list):
        for item in node:
            merge_tree(item, counter)


#: 合并后要落成的两个原子能力定义。执行器名与能力名一一对应（见 foundation 的
#: 「执行器没有原子能力声明」校验），所以新名字直接用执行器名。
#: `方式` 由「有默认值的可选」改成**必填枚举**——合并前两边的默认值本就相反，
#: 保留一个默认值等于让另一个方向变得不可见；写成必填才能把「方向」摆到台面上。
MERGED_DEFINITIONS: dict[str, dict[str, object]] = {
    "修改状态层数": {
        "类别": "效果",
        "执行器": "修改状态层数",
        "字段": {
            "方式": {"类型": "字符串", "必填": True, "选项": ["增加", "减少"]},
            "状态": {"类型": "能力", "必填": True, "允许能力": ["选择状态"]},
            "层数": {"类型": "整数", "必填": True, "最小": 1},
            "不足时是否失败": {"类型": "布尔", "默认": True},
        },
    },
    "修改状态持续": {
        "类别": "效果",
        "执行器": "修改状态持续",
        "字段": {
            "方式": {"类型": "字符串", "必填": True, "选项": ["增加", "减少"]},
            "状态": {"类型": "能力", "必填": True, "允许能力": ["选择状态"]},
            "数值": {"类型": "整数", "必填": True, "最小": 1},
        },
    },
}


def rewrite_definitions(path: pathlib.Path) -> tuple[int, int]:
    """删掉被合并掉的入口，写入合并后的定义。返回（删除数, 新增数）。"""

    definitions = json.loads(path.read_text(encoding="utf-8"))
    removed = 0
    for name in MERGES:
        if name in definitions:
            del definitions[name]
            removed += 1
    added = 0
    for name, definition in MERGED_DEFINITIONS.items():
        if name not in definitions:
            definitions[name] = definition
            added += 1
    path.write_text(
        json.dumps(definitions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return removed, added


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--落盘", action="store_true", help="写回 data/（默认只读）")
    args = parser.parse_args()

    targets = sorted((ROOT / "data").rglob("*.json"))
    counter: dict[str, int] = {name: 0 for name in MERGES}
    files = 0
    for path in targets:
        text = path.read_text(encoding="utf-8")
        if not any(name in text for name in MERGES):
            continue
        document = json.loads(text)
        merge_tree(document, counter)
        files += 1
        if args.落盘:
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

    # 生成模块里也存着大量能力树（已迁移的效果只剩引用，树在模板库这边）。
    # 它的源码是**机器生成**的，所以这里改完需要重新生成才算收敛——这是本工具
    # 唯一的临时状态，`构筑模板代码化.py` 一跑就恢复生成物的一致性。
    generated = ROOT / "game" / "core" / "combat" / "template_data.py"
    if generated.is_file():
        text = generated.read_text(encoding="utf-8")
        if any(name in text for name in MERGES):
            for old, (new, renames, _defaults) in MERGES.items():
                text = text.replace(f'"{ABILITY}": "{old}"', f'"{ABILITY}": "{new}"')
                for source, target in renames.items():
                    text = text.replace(f'"{source}":', f'"{target}":')
                    # 参数位置在模板库里可能是占位符：`"持续数值": {"$参数": "p3"}`。
                    # 它同时出现在键和值里，两处都要改，否则展开时找不到参数名。
                    text = text.replace(f'"{source}"}}', f'"{target}"}}')
                    text = text.replace(f'"${source}"', f'"${target}"')
            generated.write_text(text, encoding="utf-8")
            files += 1
            print("  已同步改写生成模块 template_data.py（建议随后重新生成模板库）")

    total = sum(counter.values())
    for name, count in counter.items():
        if count:
            print(f"  {name} -> {MERGES[name][0]}：{count} 处")
    print(f"共改写 {total} 个能力节点，涉及 {files} 个文件")

    definitions_path = ROOT / "data" / "战斗" / "定义" / "原子能力.json"
    if args.落盘:
        removed, added = rewrite_definitions(definitions_path)
        print(f"原子能力定义：删除 {removed} 个重复入口，新增 {added} 个合并定义")
    else:
        definitions = json.loads(definitions_path.read_text(encoding="utf-8"))
        removable = [name for name in MERGES if name in definitions]
        addable = [name for name in MERGED_DEFINITIONS if name not in definitions]
        print(f"原子能力定义：将删除 {len(removable)} 个入口"
              f"（{'、'.join(removable)}），新增 {len(addable)} 个"
              f"（{'、'.join(addable)}）")
        print("（试运行，未写盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
