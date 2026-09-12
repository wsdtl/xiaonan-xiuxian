"""机械化盘点：三个口径的集中度，以及「只许变散、不许变挤」的棘轮。

为什么是棘轮而不是等值判据：这一轮的目标是**把集中的地方散开**，每批改动本来就会让
分布变化——等值判据每次都会红，等于没有判据。所以这里守的是**方向**：

    集中度只能降，不能升；要往紧处改，先跑 --写基准 明确记下来。

三个口径（与 `data/战斗/内容/待补内容.md` 第六节一致）：

1. **触发时点**——`监听事件` 的 `事件` 分布；
2. **效果动词**——排除结构件之后的能力名分布；
3. **限额形态**——`每次行动最多触发` / `每场战斗最多触发` 的取值分布。

每个口径给三项读数：最大项及其占比、香农熵（越大越散）、词表里用到的种数。
另给出最集中的那个模式：**同时**挂最大事件、用最大动词的卡有多少张。

    .venv/Scripts/python.exe -X utf8 tools/机械化盘点.py            # 与基线比，变挤则非零退出
    .venv/Scripts/python.exe -X utf8 tools/机械化盘点.py --明细      # 打出完整分布表
    .venv/Scripts/python.exe -X utf8 tools/机械化盘点.py --写基准    # 抬高棘轮（改完确认变散之后）

**退出码：0 = 不比基线更集中，1 = 有口径变挤了，2 = 基准缺失或读不出来。**
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = ROOT / "tools" / "基准" / "机械化基线.json"

SURFACES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("器律", "炼器/内容/器律-*.json"),
)

#: 结构件：装配、遍历、取值、判定——它们说明「怎么算」，不说明「打出什么」。
STRUCTURAL = frozenset({
    "选择目标", "顺序执行", "事务执行", "遍历目标", "读取数值", "条件执行",
    "尝试执行", "数值条件", "被动技能", "主动技能", "固定属性加成", "监听事件",
    "选择技能", "选择状态", "组合条件", "记录战斗事实", "记录结果",
})

#: 熵容差与占比容差：允许极小波动，避免一次无关改动就红。
SHARE_TOLERANCE = 0.005
ENTROPY_TOLERANCE = 0.01


def entropy(counter: collections.Counter) -> float:
    total = sum(counter.values())
    if total <= 1:
        return 0.0
    return -sum(
        (count / total) * math.log(count / total) for count in counter.values() if count
    )


def scan() -> dict[str, object]:
    events: collections.Counter = collections.Counter()
    verbs: collections.Counter = collections.Counter()
    limits: collections.Counter = collections.Counter()
    event_cards: dict[str, set[str]] = collections.defaultdict(set)
    verb_cards: dict[str, set[str]] = collections.defaultdict(set)
    card_events: dict[str, set[str]] = collections.defaultdict(set)
    total_cards = 0

    def walk(node: object, card_id: str) -> None:
        if isinstance(node, dict):
            ability = node.get("能力")
            if ability == "监听事件":
                name = node.get("事件")
                if isinstance(name, str) and name:
                    events[name] += 1
                    event_cards[name].add(card_id)
                    card_events[card_id].add(name)
                # 限额写在**监听节点**上，不在主动技能里——第一版放错了地方，读数是 0。
                for key in ("每次行动最多触发", "每场战斗最多触发"):
                    if key in node:
                        limits[f"{key}={node[key]}"] += 1
            if isinstance(ability, str) and ability and ability not in STRUCTURAL:
                verbs[ability] += 1
                verb_cards[ability].add(card_id)
            for value in node.values():
                walk(value, card_id)
        elif isinstance(node, list):
            for value in node:
                walk(value, card_id)

    for section, pattern in SURFACES:
        for path in sorted(ROOT.glob(f"data/{pattern}")):
            for entry in json.loads(path.read_text(encoding="utf-8")):
                total_cards += 1
                walk(entry, str(entry["编号"]))

    top_event = events.most_common(1)[0][0] if events else ""
    top_verb = verbs.most_common(1)[0][0] if verbs else ""
    # 卡级：一张卡的监听节点里，触发时点只有一种的，叫「单一触发卡」。
    # 早先我量的是「同时出现过最大事件与最大动词的卡」，那张表读成 60%——但一张卡有
    # 近十个监听节点，两者都出现太容易，那个口径把「都出现过」当成了「都是这个」。
    single_trigger = sum(1 for names in card_events.values() if len(names) == 1)
    multi_trigger = sum(1 for names in card_events.values() if len(names) > 1)

    def axis(counter: collections.Counter, top: str) -> dict[str, object]:
        total = sum(counter.values())
        return {
            "最大项": top,
            "最大项次数": counter[top],
            "最大项占比": round(counter[top] / total, 4) if total else 0.0,
            "熵": round(entropy(counter), 4),
            "种数": len(counter),
        }

    return {
        "卡数": total_cards,
        "触发时点": axis(events, top_event),
        "效果动词": axis(verbs, top_verb),
        "限额形态": axis(limits, limits.most_common(1)[0][0] if limits else ""),
        "卡级": {
            "单一触发卡": single_trigger,
            "单一触发占比": round(single_trigger / total_cards, 4) if total_cards else 0.0,
            "多时点卡": multi_trigger,
            "最大事件": top_event,
            "最大动词": top_verb,
        },
        "_分布": {
            "触发时点": events.most_common(),
            "效果动词": verbs.most_common(),
            "限额形态": limits.most_common(),
        },
    }


def render(reading: dict[str, object], detail: bool) -> None:
    print(f"卡数 {reading['卡数']}")
    for name in ("触发时点", "效果动词", "限额形态"):
        row = reading[name]
        print(
            f"  {name}：最大项 {row['最大项']} {row['最大项次数']} 次"
            f"，占比 {row['最大项占比']:.1%}，熵 {row['熵']:.3f}，词表用到 {row['种数']} 种"
        )
    card = reading["卡级"]
    print(
        f"  卡级：触发时点只有一种的卡 {card['单一触发卡']} 张"
        f"（{card['单一触发占比']:.1%}），多时点卡 {card['多时点卡']} 张"
    )
    if detail:
        for name, rows in reading["_分布"].items():
            print(f"\n===== {name} =====")
            for key, count in rows:
                print(f"   {count:>5}  {key}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--基准", default=str(DEFAULT_BASELINE), help="入库基线")
    parser.add_argument("--写基准", action="store_true", help="把当前读数写成新基线（抬高棘轮）")
    parser.add_argument("--明细", action="store_true", help="打出完整分布表")
    args = parser.parse_args()

    reading = scan()
    render(reading, args.明细)
    stored = {key: value for key, value in reading.items() if not key.startswith("_")}

    baseline = pathlib.Path(args.基准)
    if args.写基准:
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(
            json.dumps(stored, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
            encoding="utf-8",
        )
        print(f"\n已写入 {baseline}（棘轮已抬高）")
        return 0

    if not baseline.is_file():
        print(f"\n基线不存在：{baseline}；先跑一次 --写基准")
        return 2
    try:
        expected = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"基线无法读取：{exc}")
        return 2

    worse: list[str] = []
    for name in ("触发时点", "效果动词", "限额形态"):
        now, was = stored[name], expected[name]
        if now["最大项占比"] > was["最大项占比"] + SHARE_TOLERANCE:
            worse.append(
                f"{name} 更集中：{was['最大项']} {was['最大项占比']:.1%}"
                f" → {now['最大项']} {now['最大项占比']:.1%}"
            )
        elif now["熵"] < was["熵"] - ENTROPY_TOLERANCE:
            worse.append(f"{name} 更单调：熵 {was['熵']:.3f} → {now['熵']:.3f}")
    now_card, was_card = stored["卡级"], expected["卡级"]
    if now_card["单一触发占比"] > was_card["单一触发占比"] + SHARE_TOLERANCE:
        worse.append(
            f"单一触发卡变多了：{was_card['单一触发占比']:.1%}"
            f" → {now_card['单一触发占比']:.1%}"
        )

    print()
    if worse:
        print("变挤了 " + str(len(worse)) + " 处（这一轮的目标是把集中的地方散开）：")
        for line in worse:
            print(f"  {line}")
        return 1
    print(f"不比基线更集中（基线单一触发卡 {was_card['单一触发占比']:.1%}，"
          f"最大事件 {was_card['最大事件']}，最大动词 {was_card['最大动词']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
