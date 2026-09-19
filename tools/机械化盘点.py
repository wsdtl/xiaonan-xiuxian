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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from 全库扫描 import 全库文档  # noqa: E402
from 构筑模板展开 import load_build_json as _load_build_json  # noqa: E402
DEFAULT_BASELINE = ROOT / "tools" / "基准" / "机械化基线.json"

SURFACES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("器律", "物品/炼器/内容/器律-*.json"),
)

#: 引擎 `_value_read` 支持的读取来源（见 `game/core/combat/mechanics.py`）。
#: 盘点里少了哪一个，就是「空着的机制」——负责人口径：没有的机制可以考虑用上。
ENGINE_ORIGINS = tuple(
    json.loads((ROOT / "data/战斗/定义/原子能力.json").read_text(encoding="utf-8"))
    ["读取数值"]["字段"]["来源"]["选项"]
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
    sources: collections.Counter = collections.Counter()
    limits: collections.Counter = collections.Counter()
    stats: collections.Counter = collections.Counter()
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
            if ability == "读取数值":
                # 第三条轴动的是「缩放从哪来」而不是动词本身：卡内计数器是现状，
                # 换成对方属性 / 事件数值 / 已损失血气比才是散开。
                sources[str(node.get("来源") or "（未写）")] += 1
            if ability == "固定属性加成":
                # 第五条轴：**数值档**。气机 703 张（36% 的语料）没有监听节点，
                # 前四条轴一条都量不到它；它的机械化就在「每个属性一个死值」上
                # （`命中率=3` 曾出现在 36 张上）。所以按 `属性=值` 的组合数一遍。
                for key, value in dict(node.get("属性") or {}).items():
                    stats[f"{key}={value}"] += 1
            for value in node.values():
                walk(value, card_id)
        elif isinstance(node, list):
            for value in node:
                walk(value, card_id)

    for section, pattern in SURFACES:
        for path in sorted(ROOT.glob(f"data/{pattern}")):
            for entry in _load_build_json(path):
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
        "缩放来源": axis(
            sources, sources.most_common(1)[0][0] if sources else ""
        ),
        "数值档": axis(stats, stats.most_common(1)[0][0] if stats else ""),
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


def gaps() -> dict[str, object]:
    """空位：引擎支持、但全库没在用的机制。

    负责人口径是「**每个机制尽量要平均，没有的机制可以考虑使用上**」——所以读数不能只报
    「哪里挤」，还要报「哪里空着」。只报事实，不自动判定好坏。

    **扫全库，不只四类构筑卡**：口径说的是「全库没人用」，只扫 `SURFACES` 会把战丹 / 伤势 /
    战场环境里已经用上的来源报成空位（`目标当前护盾` 就被这样误报过）。读取走
    `全库扫描.全库文档()`，模板引用在那里已经展开。
    """
    origins: collections.Counter[str] = collections.Counter()
    fields: collections.Counter[str] = collections.Counter()
    tags: collections.Counter[str] = collections.Counter()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("能力") == "读取数值":
                origins[str(node.get("来源") or "固定值")] += 1
                for key in ("百分比", "最低值", "最高值", "固定值"):
                    if key in node:
                        fields[key] += 1
            value = node.get("标签")
            if isinstance(value, list):
                # 标签挂在很多种节点上，**必须分开数**：`主动技能` 的标签是技能标签（词表），
                # `修改战斗关联`/`修改事件标签` 的标签是另一套东西。混在一起会把
                # 「技能标签只有 1 种」这个真问题掩盖成「113 种、很丰富」。
                for item in value:
                    tags[f"{node.get('能力') or '（无名）'}·{item}"] += 1
            for nested in node.values():
                walk(nested)
        elif isinstance(node, list):
            for nested in node:
                walk(nested)

    for _相对, 文档 in 全库文档():
        walk(文档)
    unused = [name for name in ENGINE_ORIGINS if name not in origins]
    return {"未用来源": unused, "字段": fields, "标签": tags}


def render(reading: dict[str, object], detail: bool) -> None:
    print(f"卡数 {reading['卡数']}")
    for name in ("触发时点", "效果动词", "限额形态", "缩放来源", "数值档"):
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
    hole = gaps()
    print(f"  空位：未启用的读取来源 {len(hole['未用来源'])} 种"
          f"（{' '.join(hole['未用来源']) or '无'}）")
    used = " · ".join(f"{key} {hole['字段'][key]}" for key in ("百分比", "最低值", "最高值", "固定值"))
    print(f"  读取数值 字段用量：{used}")
    if hole["标签"]:
        skill_tags = {k.split("·", 1)[1]: v for k, v in hole["标签"].items()
                      if k.startswith("主动技能·")}
        other = sum(v for k, v in hole["标签"].items() if not k.startswith("主动技能·"))
        print(f"  技能标签（主动技能）：{len(skill_tags)} 种"
              f" · {' '.join(f'{k} {v}' for k, v in sorted(skill_tags.items(), key=lambda kv: -kv[1])[:6]) or '无'}")
        print(f"  其它标签（战斗关联/事件标签/条件…）：{other} 个 · "
              f"{len(hole['标签']) - len(skill_tags)} 种")
    else:
        print("  技能标签词表：**一个都没在用**")
    if detail:
        for name, rows in reading["_分布"].items():
            print(f"\n===== {name} =====")
            for key, count in rows:
                print(f"   {count:>5}  {key}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--基准", default=str(DEFAULT_BASELINE), help="入库基线")
    parser.add_argument("--写基准", action="store_true", help="把当前读数写成新基线（抬高棘轮）")
    parser.add_argument("--备注", default="", help="与 --写基准 同用：记下这次为什么抬高棘轮")
    parser.add_argument("--明细", action="store_true", help="打出完整分布表")
    args = parser.parse_args()

    reading = scan()
    render(reading, args.明细)
    stored = {key: value for key, value in reading.items() if not key.startswith("_")}

    baseline = pathlib.Path(args.基准)
    if args.写基准:
        旧备注 = ""
        if baseline.is_file():
            try:
                旧备注 = str(json.loads(baseline.read_text(encoding="utf-8")).get("备注") or "")
            except (OSError, json.JSONDecodeError):
                旧备注 = ""
        # 棘轮是**按名字**量的：改过口径（例如两个动词合并成一个名字）之后，旧基线
        # 与当前读数不是同一把尺子，必须留下为什么抬高的依据。没写新的就沿用旧的。
        if args.备注 or 旧备注:
            stored["备注"] = args.备注 or 旧备注
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
    for name in ("触发时点", "效果动词", "限额形态", "缩放来源", "数值档"):
        now, was = stored.get(name), expected.get(name)
        if not now or not was:
            # 新加的轴：旧基线里没有这一项。跳过比较，`--写基准` 之后才纳入棘轮
            # （否则加一条新轴就会让所有旧基线当场崩掉）。
            print(f"  （{name}：基线里还没有，本轮跳过比较——跑一次 --写基准 即纳入）")
            continue
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
