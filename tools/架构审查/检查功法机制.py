"""功法机制判据（细分版）：9 族 → 31 细类，按签名原子能力自动归类。

底座撑得住（第 20/22 轮实测）：65 项原子能力、52 项已被功法用到；八项"闲置机制"
（转移伤害 / 抵挡致命伤害 / 转化事件 / 修改事件标签 / 修改行动意图 / 概率条件 /
随机数值 / 组合条件）**在模板库里都有现成主体**，其中转化事件、修改事件标签已被真意引用。

判据盯四件事：
  一、单**细类** ≤ 8%
  二、单**族** ≤ 20%
  三、每个细类至少 3 张（类别细了，每类都得真有货，否则这一类等于不存在）
  四、八项闲置机制每项至少出现在 3 张卡里（它们是 反伤/分摊/换命/取消/移祸/改判/改标签/赌运 的弹药）

跑法：`python -X utf8 tools/架构审查/检查功法机制.py`
（骨架唯一性那条在 `检查功法签名.py`：一个防"换数字"，一个防"一窝蜂"。）
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
ARTS = ROOT / "data" / "战斗" / "内容" / "功法"
DEFINITION = ROOT / "data" / "战斗" / "定义" / "原子能力.json"

CLASS_QUOTA = 0.08
FAMILY_QUOTA = 0.20
CLASS_MIN_CARDS = 3
COLD_MIN_CARDS = 3

COLD_ABILITIES = (
    "转移伤害",
    "抵挡致命伤害",
    "修改事件标签",
    "修改行动意图",
    "转化事件",
    "随机数值",
    "概率条件",
    "组合条件",
)

#: 归类规则：从特到泛，第一个命中的签名决定细类。
RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("反制", "取消", ("取消事件",)),
    ("反制", "改标签", ("修改事件标签",)),
    ("反制", "改判", ("修改判定",)),
    ("反制", "移祸", ("修改事件目标", "修改事件数值")),
    ("借力", "分摊", ("分摊伤害",)),
    ("借力", "反伤", ("转移伤害",)),
    ("借力", "借资源", ("转移资源", "修改归属")),
    ("献祭", "换命", ("抵挡致命伤害", "复活")),
    ("献祭", "燃血", ("支付代价",)),
    ("献祭", "焚身", ("消耗资源",)),
    ("变化", "赌运", ("概率条件", "随机数值")),
    ("变化", "复式条件", ("组合条件",)),
    ("位序", "抢先", ("修改行动条",)),
    ("位序", "乱序", ("修改行动意图",)),
    ("位序", "后发", ("监听事件",)),
    ("形态", "化身", ("修改战场规则",)),
    ("形态", "变招", ("修改技能", "修改战术")),
    ("形态", "架势", ("切换形态",)),
    ("场域", "构造物", ("创建战斗对象", "移除战斗对象")),
    ("连携", "回响", ("回放效果",)),
    ("连携", "传功", ("复制技能", "转移状态")),
    ("连携", "同气", ("触发技能",)),
    ("相克", "崩解", ("转化事件",)),
    ("相克", "逆相", ("类型条件",)),
    ("相克", "相克", ("状态条件", "标签条件")),
    ("蓄爆", "自燃", ("移除状态",)),
    ("蓄爆", "蓄势", ("修改状态层数", "修改构筑计量")),
    ("蓄爆", "印记", ("添加状态",)),
)
FALLBACK = ("即时", "直伤")


def abilities_of(card: dict, clusters: dict) -> set[str]:
    """这张卡用到的原子能力集合（模板编号 → 该模板用了哪些能力）。"""

    found: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            name = node.get("模板")
            if isinstance(name, str):
                for ability in (clusters.get(name) or [[]])[0]:
                    found.add(str(ability))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(card)
    return found


def classify(abilities: set[str]) -> tuple[str, str]:
    for family, name, keys in RULES:
        if abilities & set(keys):
            return family, name
    return FALLBACK


def load_cards() -> list[dict]:
    found: list[dict] = []
    for path in sorted(ARTS.rglob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                found.append(item)
    return found


def main() -> int:
    from game.core.combat.template_data import TEMPLATE_CLUSTERS

    all_cards = load_cards()
    total = len(all_cards)
    known = len(json.loads(DEFINITION.read_text(encoding="utf-8")))
    families: collections.Counter[str] = collections.Counter()
    classes: collections.Counter[str] = collections.Counter()
    usage: collections.Counter[str] = collections.Counter()
    per_card: list[set[str]] = []
    for card in all_cards:
        abilities = abilities_of(card, TEMPLATE_CLUSTERS)
        per_card.append(abilities)
        usage.update(abilities)
        family, name = classify(abilities)
        families[family] += 1
        classes[f"{family}/{name}"] += 1
    print(f"功法 {total} 张 ｜ 原子能力用到 {len(usage)} / {known} 项 ｜ 细类 {len(classes)} 个有卡")

    failures = 0
    print("=== 细类分布（单类上限 %.0f%%，每类至少 %d 张）" % (CLASS_QUOTA * 100, CLASS_MIN_CARDS))
    for name, count in classes.most_common():
        share = count / total
        ok = share <= CLASS_QUOTA and count >= CLASS_MIN_CARDS
        failures += not ok
        print(f"   [{'通过' if ok else '失败'}] {name}：{count} 张（{share * 100:.1f}%）")

    print("=== 族分布（单族上限 %.0f%%）" % (FAMILY_QUOTA * 100))
    for name, count in families.most_common():
        ok = count / total <= FAMILY_QUOTA
        failures += not ok
        print(f"   [{'通过' if ok else '失败'}] {name}：{count} 张（{count / total * 100:.1f}%）")

    missing = [
        f"{family}/{name}"
        for family, name, _ in RULES
        if classes.get(f"{family}/{name}", 0) < CLASS_MIN_CARDS
    ]
    failures += len(missing)
    print(f"[{'通过' if not missing else '失败'}] 细类覆盖：{len(classes)} 类有卡，"
          f"缺员的 {len(missing)} 类 —— {'、'.join(missing[:12])}{' …' if len(missing) > 12 else ''}")

    print(f"=== 闲置弹药（每项 ≥ {COLD_MIN_CARDS} 张）")
    for name in COLD_ABILITIES:
        cards_with = sum(1 for abilities in per_card if name in abilities)
        ok = cards_with >= COLD_MIN_CARDS
        failures += not ok
        print(f"   [{'通过' if ok else '失败'}] {name}：{cards_with} 张")

    print(f"总账：失败 {failures} 组")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
