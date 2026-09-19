"""把「属性怎么被引擎读」这件事从代码里的暗规则补成数据里的明字段，并把加成类基准补到 100。

## 为什么

改动前，同一个「百分比属性」有两种互相矛盾的读法，只能靠调用点记：

- `game/core/combat/mechanics.py` 的 `_attribute_ratio` 把 `默认值` 当基准（`100` → ×1.0）；
- `game/core/combat/engine.py` 的 `_percent` 把 `默认值` 当兜底，调用点自己写 `1 + …`。

于是「伤害加成 20」= +20%，而「治疗效果 100」= 不缩放；「伤害减免 20」又要减而不是加。
这三类混在一起，全靠 `+` / `-` / `*` 的写法区分，写错了只在真实对局里静默出错。

## 这一步做什么

1. 每个属性补一个 `口径` 字段（数值 / 加成 / 倍率 / 概率 / 减免 / 比率），引擎按它读；
2. **加成类**（`伤害加成`、`普通攻击威力`、`技能威力`、`治疗加成`、`受疗加成`、
   `护盾加成`、`受盾加成`）的基准从 0 补到 **100**，与 `治疗效果` / `护盾强度` 一致：
   不增不减就是 100，加两成写 120。上下限同步 +100，语义不变。

**只动基数，不动任何卡面数值**：状态 `属性`、形态 `属性变化`、`固定属性加成`、
突破丹 `永久属性` 写的都是「加在基数上的差值」，基数平移后差值原样有效
（实测全库 326 处这类写入，没有一处是绝对基数写法）。

用法：
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/属性口径与基准.py           # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/属性口径与基准.py --落盘
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
路径 = ROOT / "data" / "战斗" / "定义" / "属性.json"

#: 每个属性的读法。这张表是这一步的**唯一依据**：引擎、校验器、工具都从这里之外的地方
#: 读同一份数据，不再各写一套。
口径表: dict[str, str] = {
    "血气上限": "数值",
    "精神上限": "数值",
    "攻击": "数值",
    "防御": "数值",
    "速度": "数值",
    "护盾上限": "数值",
    "固定穿透": "数值",
    "血气恢复": "数值",
    "精神恢复": "数值",
    "命中率": "概率",
    "闪避率": "概率",
    "暴击率": "概率",
    "抗暴率": "概率",
    "格挡率": "概率",
    "破格率": "概率",
    "连击率": "概率",
    "反击率": "概率",
    "反伤率": "概率",
    "吸血率": "概率",
    "控制命中率": "概率",
    "控制抵抗率": "概率",
    "暴击伤害": "倍率",
    "连击伤害": "倍率",
    "暴击伤害减免": "减免",
    "格挡减伤": "减免",
    "伤害减免": "减免",
    "韧性": "减免",
    "冷却缩减": "减免",
    "精神消耗修正": "减免",
    "比例穿透": "比率",
    "伤害加成": "加成",
    "普通攻击威力": "加成",
    "技能威力": "加成",
    "治疗加成": "加成",
    "受疗加成": "加成",
    "护盾加成": "加成",
    "受盾加成": "加成",
    "治疗效果": "加成",
    "护盾强度": "加成",
}

字段顺序 = ("默认值", "单位", "最小单位", "最低值", "最高值", "显示", "口径", "说明")


def 建条目(名字: str, 条目: dict) -> tuple[dict, list[str]]:
    改动: list[str] = []
    新条目 = dict(条目)
    if 新条目.get("口径") != 口径表[名字]:
        新条目["口径"] = 口径表[名字]
        改动.append(f"补口径 {口径表[名字]}")
    if 口径表[名字] == "加成" and float(新条目["默认值"]) != 100.0:
        偏移 = 100.0 - float(新条目["默认值"])
        for 字段 in ("默认值", "最低值", "最高值"):
            值 = float(新条目[字段]) + 偏移
            新条目[字段] = int(值) if 值.is_integer() else 值
        改动.append(f"基准 {偏移:+.0f}（默认值 -> 100，上下限同步）")
    顺序 = {名字: 序号 for 序号, 名字 in enumerate(字段顺序)}
    新条目 = dict(sorted(新条目.items(), key=lambda 项: 顺序.get(项[0], len(顺序))))
    return 新条目, 改动


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--落盘", action="store_true", help="写回数据文件")
    args = parser.parse_args()

    文档 = json.loads(路径.read_text(encoding="utf-8"))
    未登记 = sorted(set(文档) - set(口径表))
    缺失 = sorted(set(口径表) - set(文档))
    if 未登记 or 缺失:
        print(f"口径表与属性表不齐：未登记 {未登记}；表里多出 {缺失}")
        return 1

    新文档: dict[str, dict] = {}
    总改动 = 0
    for 名字, 条目 in 文档.items():
        新条目, 改动 = 建条目(名字, 条目)
        新文档[名字] = 新条目
        if 改动:
            总改动 += 1
            print(f"  {名字:<8} {'；'.join(改动)}")

    print(f"属性 {len(新文档)} 个；本次改动 {总改动} 个")
    if not 总改动:
        print("已是目标形态，重跑无效果")
        return 0
    if not args.落盘:
        print("（试算，未落盘；加 --落盘 写入）")
        return 0
    路径.write_text(
        json.dumps(新文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"已写入 {路径.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
