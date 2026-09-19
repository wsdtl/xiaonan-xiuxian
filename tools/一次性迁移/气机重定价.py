"""气机重定价：把「每个属性一个死值」改成「按卡的结构定价」。

气机 703 张的结构是**完整组合网格**：37 个属性键 × 两两组合 = 666 张 + 37 张单属性，
但每个键的数值是**死值**（`命中率=3` 出现在 36 张上、`闪避率=2` 36 张、`护盾上限=30` 36 张…）。
玩家看到的永远是同一组数字，属性组合的差别在数值上体现不出来。

改成按卡的结构定价（有取舍，不是随机撒）：

| 卡的结构 | 系数 | 设计含义 |
| --- | --- | --- |
| 单属性 | **×1.6** | 专家型：只修一门，给足 |
| 同族双属性 | **×1.35** | 协同：两门同源（如 暴击率+暴击伤害），互相加成 |
| 跨族双属性 | **×0.7** | 摊薄：两门不相干，各让一步 |

上限类（血气上限 / 精神上限 / 护盾上限）取整到 5 的倍数，其余取整到整数（最小 1）。

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/气机重定价.py            # 试算（打印数值档变化）
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/气机重定价.py --写入 --授权集 _授权.json

**退出码：0 = 正常，2 = 没找到可改处。**
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PATTERN = "data/战斗/内容/气机/气机-*.json"

#: 属性分族：同族配对算协同，跨族算摊薄。
FAMILIES = {
    "攻击": {"攻击", "普通攻击威力", "技能威力", "伤害加成", "固定穿透", "比例穿透",
             "破格率", "连击率", "连击伤害", "暴击率", "暴击伤害", "吸血率", "反击率", "反伤率"},
    "防御": {"防御", "伤害减免", "韧性", "格挡率", "格挡减伤", "抗暴率", "暴击伤害减免"},
    "资源": {"血气上限", "精神上限", "血气恢复", "精神恢复", "护盾上限", "护盾加成",
             "受盾加成", "精神消耗修正", "冷却缩减"},
    "机动": {"命中率", "闪避率", "速度"},
    "控制": {"控制命中率", "控制抵抗率"},
    "辅助": {"治疗加成", "受疗加成"},
}
CAPS = {"血气上限", "精神上限", "护盾上限"}


def family_of(key: str) -> str:
    for name, members in FAMILIES.items():
        if key in members:
            return name
    return "其他"


def multiplier(keys: list[str]) -> float:
    # 基准值本来就小（2~4），档距太窄会被取整吃掉，所以三档拉开：
    # 专家 1.6 / 协同 1.35 / 摊薄 0.7 —— 保证整数化之后仍能看出三档。
    if len(keys) == 1:
        return 1.6
    return 1.35 if family_of(keys[0]) == family_of(keys[1]) else 0.7


def rescale(key: str, value: object, factor: float) -> int:
    amount = float(value) * factor
    if key in CAPS:
        return max(5, int(round(amount / 5.0)) * 5)
    return max(1, int(round(amount)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--写入", action="store_true", help="默认只试算，加这个才落盘")
    parser.add_argument("--授权集", default="", help="把授权卡清单写到这个 json")
    args = parser.parse_args()

    before: collections.Counter = collections.Counter()
    after: collections.Counter = collections.Counter()
    grant: dict[str, list[str]] = {}
    changed = 0
    for path in sorted(ROOT.glob(PATTERN)):
        entries = json.loads(path.read_text(encoding="utf-8"))
        cards: list[str] = []
        for entry in entries:
            keys: list[str] = []

            def collect(node: object) -> None:
                if isinstance(node, dict):
                    if node.get("能力") == "固定属性加成":
                        keys.extend(str(key) for key in dict(node.get("属性") or {}))
                    for value in node.values():
                        collect(value)
                elif isinstance(node, list):
                    for value in node:
                        collect(value)

            collect(entry)
            if not keys:
                continue
            factor = multiplier(keys)
            touched = False

            def apply(node: object) -> None:
                nonlocal touched
                if isinstance(node, dict):
                    if node.get("能力") == "固定属性加成":
                        stats = node.get("属性")
                        if isinstance(stats, dict):
                            for key, value in list(stats.items()):
                                before[f"{key}={value}"] += 1
                                new_value = rescale(str(key), value, factor)
                                after[f"{key}={new_value}"] += 1
                                if new_value != value:
                                    stats[key] = new_value
                                    touched = True
                    for value in node.values():
                        apply(value)
                elif isinstance(node, list):
                    for value in node:
                        apply(value)

            apply(entry)
            if touched:
                changed += 1
                cards.append(str(entry["编号"]))
        if cards:
            grant[path.relative_to(ROOT).as_posix()] = sorted(cards)
            if args.写入:
                path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")

    if not changed:
        print("没找到可改处。")
        return 2
    print(f"改动 {changed} 张卡")
    keys_seen = sorted({key.split("=")[0] for key in before})
    print(f"\n{'属性':<14}{'原值分布':<18}{'新值分布'}")
    for key in keys_seen:
        was = {k.split("=")[1]: v for k, v in before.items() if k.startswith(key + "=")}
        now = {k.split("=")[1]: v for k, v in after.items() if k.startswith(key + "=")}
        print(f"{key:<14}{' '.join(f'{k}×{v}' for k, v in sorted(was.items())):<18}"
              f"{' '.join(f'{k}×{v}' for k, v in sorted(now.items()))}")
    if args.授权集:
        pathlib.Path(args.授权集).write_text(
            json.dumps(grant, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"授权集写入 {args.授权集}")
    if not args.写入:
        print("这是试算；确认后再加 --写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
