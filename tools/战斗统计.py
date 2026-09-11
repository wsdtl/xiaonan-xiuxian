"""战斗体统计：把一套数值打起来是什么样，量成可比的分布。

`tools/语料对照.py` 比的是「有没有变」（摘要是否相等），是给改名、搬位置用的。
调平衡要的正好相反——**目标就是让它变**，所以需要另一个视角：

    一场打多少行动？一方死要几下？伤害占血上限多少？
    命中/暴击/格挡/闪避的实际发生率是多少？精神够不够用？战斗是不是被行动上限截断？

这些数出来了，调数值才有靶子；没有它们，改完只会有「变了 1264 处」这种无用信息。

    .venv/Scripts/python.exe -X utf8 tools/战斗统计.py
    .venv/Scripts/python.exe -X utf8 tools/战斗统计.py --数据 "<另一份 data 目录>"
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import dataclasses
import io
import json
import pathlib
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatantSpec,
    CombatRequest,
)

#: 陪练属性取语料同一套，保证和 `语料对照.py` 可比。
ATTRS = {
    "血气上限": 1200, "精神上限": 400, "攻击": 150, "防御": 60, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 0, "伤害减免": 0,
}
SURFACES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("器律", "炼器/内容/器律-*.json"),
)


def corpus(root: pathlib.Path):
    items = []
    for section, pattern in SURFACES:
        for path in sorted(root.glob(pattern)):
            for entry in json.loads(path.read_text(encoding="utf-8")):
                items.append((section, str(entry["编号"])))
    return items


def fight_unresolved(raw) -> bool:
    """战斗是否未分胜负。

    必须读引擎自己的结论，不能看「双方血气都大于 0」——有的卡会让一方
    `active=False`（遁走、入定、放逐一类），引擎据此正常判出胜负，
    但那一方的血气还满着。按血气判会把这类**已结束**的战斗错记成未决。
    """

    for event in raw.get("events") or ():
        if event.get("kind") == "战斗结束":
            return str((event.get("values") or {}).get("结果") or "") == "未分胜负"
    return False


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return ordered[index]


def summarize(label: str, values: list[float], out, unit: str = "") -> None:
    if not values:
        out.write(f"  {label}: 无样本\n")
        return
    out.write(
        f"  {label}: 中位 {statistics.median(values):.2f}{unit}"
        f" · 均值 {statistics.mean(values):.2f}{unit}"
        f" · p10 {percentile(values, 0.10):.2f} · p90 {percentile(values, 0.90):.2f}"
        f" · 最小 {min(values):.2f} · 最大 {max(values):.2f}\n"
    )


def pools(root: pathlib.Path) -> dict[str, list[str]]:
    """四类卡片池，按编号序，用来拼满构筑。"""

    return {
        section: [cid for section, cid in corpus(root) if section == section_name]
        for section_name, section in (
            ("功法", "功法"), ("真意", "真意"), ("器律", "器律"),
        )
    } | {
        "气机": [
            str(entry["编号"])
            for path in sorted(root.glob("战斗/内容/气机/气机-*.json"))
            for entry in json.loads(path.read_text(encoding="utf-8"))
        ]
    }


def full_builds(root: pathlib.Path, count: int) -> list[tuple[tuple[str, str], ...]]:
    """拼 `count` 套满构筑：功法 6 / 真意 6 / 气机 6 / 器律 4。

    槽位取自 `角色/规则/主体/人物.json` 的 `修行槽位` 与本命武器孔位。
    取法是确定性跨步，保证可复现，也让每套构筑取到池子里不同的一段。
    """

    table = pools(root)
    slots = (("功法", 6), ("真意", 6), ("气机", 6), ("器律", 4))
    builds = []
    for index in range(count):
        entries = []
        for section, size in slots:
            pool = table[section]
            if not pool:
                continue
            for offset in range(size):
                entries.append((section, pool[(index * size + offset) % len(pool)]))
        builds.append(tuple(entries))
    return builds


def level_attributes(root: pathlib.Path, level: int) -> dict[str, float]:
    """按等级现算属性：`人物.属性覆盖` 当 1 级基准，叠 `修士修炼` 的每级成长。

    `等级=0` 时原样返回陪练配置，保证和 `语料对照.py` 可比。
    """

    if level <= 0:
        return dict(ATTRS)
    spec = json.loads((root / "战斗/定义/属性.json").read_text(encoding="utf-8"))
    attrs = {
        str(name): float(body.get("默认值") or 0)
        for name, body in spec.items()
        if isinstance(body, dict) and "默认值" in body
    }
    hero = json.loads(
        (root / "角色/规则/主体/人物.json").read_text(encoding="utf-8")
    )
    attrs.update({str(k): float(v) for k, v in (hero.get("属性覆盖") or {}).items()})
    growth = json.loads(
        (root / "角色/规则/成长/修士修炼.json").read_text(encoding="utf-8")
    )["属性成长"]["每级"]
    for name, step in growth.items():
        if name in attrs:
            attrs[name] += float(step) * max(0, level - 1)
    return attrs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--数据", dest="data", default=str(ROOT / "data"))
    parser.add_argument("--报告", dest="report", default="_战斗统计.txt")
    parser.add_argument("--上限", dest="limit", type=int, default=60)
    parser.add_argument(
        "--空白", action="store_true",
        help="不装任何构筑，双方只靠普通攻击。量的是**数值底座**（属性/伤害公式/判定），"
             "把卡的因素剔干净",
    )
    parser.add_argument("--等级", dest="等级", type=int, default=0,
                        help="按该等级现算属性（人物属性覆盖 + 修士修炼每级成长）；0 = 用陪练配置")
    parser.add_argument("--种子", dest="种子", type=int, default=1,
                        help="采样组数；空白组双方对称，只有骰子随机，靠多组种子取分布")
    parser.add_argument("--满构筑", action="store_true",
                        help="按人物槽位（功法6/真意6/气机6/器律4）拼满构筑对战，"
                             "这才是真实对局规模；默认语料是每边 1 张卡")
    parser.add_argument("--构筑数", dest="构筑数", type=int, default=40,
                        help="满构筑模式下采样多少套构筑")
    args = parser.parse_args()

    root = pathlib.Path(args.data).resolve()
    core = build_game_services(data_dir=root).core

    # 属性按等级现算：人物 `属性覆盖` 当 1 级基准，再叠 `修士修炼` 的每级成长。
    attrs = level_attributes(root, args.等级)
    seeds = [20260911 + index * 7919 for index in range(max(1, args.种子))]

    # 每个任务 =（标签, 这份构筑的卡列表, 种子）；卡列表为空即空白组。
    tasks: list[tuple[str, tuple[tuple[str, str], ...], int]] = []
    if args.空白:
        # 不装卡：双方完全对称，只有骰子有随机性，所以靠多组种子取分布。
        tasks = [("空白", (), s) for s in seeds]
    elif args.满构筑:
        for index, entries in enumerate(full_builds(root, args.构筑数)):
            tasks.append((f"满构筑{index}", entries, seeds[index % len(seeds)]))
    else:
        for index, item in enumerate(corpus(root)):
            tasks.append((f"{item[0]}:{item[1]}", (item,), seeds[index % len(seeds)]))
    actions: list[float] = []
    dealt: list[float] = []          # 单次造成伤害
    ratios: list[float] = []         # 总伤害 / 双方起始血上限之和
    spirit_left: list[float] = []
    health_left: list[float] = []
    skills: list[float] = []         # 每场技能施放次数
    counts = collections.Counter()
    unresolved = 0
    total = 0
    failures: list[str] = []
    caps_seen: set[tuple[float, float]] = set()

    hp_pool = attrs["血气上限"] * 2

    for label, entries, seed in tasks:
        def side(pid: str) -> CombatantSpec:
            refs = tuple(
                CombatBuildRef(section, cid, instance_id=f"{pid}:{cid}", born_order=order)
                for order, (section, cid) in enumerate(entries)
            )
            return CombatantSpec(
                id=pid, name=pid, attributes=dict(attrs), build=refs,
            )

        try:
            raw = dataclasses.asdict(asyncio.run(core.combat.execute(CombatRequest(
                left_team=(side("L"),), right_team=(side("R"),),
                seed=seed, action_limit=args.limit,
            ))))
        except Exception as exc:  # noqa: BLE001
            # 必须点名是**哪一套**炸了：静默计数会把内容 bug 藏进「样本 39 场」里。
            counts["战斗抛错"] += 1
            entries_text = "+".join(cid for _section, cid in entries) or label
            failures.append(f"{label}\t{type(exc).__name__}: {exc}\t{entries_text}")
            continue

        total += 1
        # `actions` 是行动数本身（int），不是行动列表。
        actions.append(float(raw.get("actions") or 0))
        events = raw.get("events") or ()
        for event in events:
            counts[event.get("kind")] += 1
            if event.get("kind") == "造成伤害后":
                amount = float(event.get("amount") or 0.0)
                if amount > 0:
                    dealt.append(amount)
        damage = sum(float(e.get("amount") or 0.0) for e in events
                     if e.get("kind") == "造成伤害后")
        ratios.append(damage / hp_pool)
        skills.append(float(counts_of(events, "技能施放后")))
        for key in ("left", "right"):
            side_data = raw.get(key) or {}
            # 分母必须用**运行时上限**（含气机等加成），不能用等级推出的基准值
            # —— 后者偏小会把「余量占比」算成大于 1，看着像资源溢出。
            runtime = side_data.get("attributes") or {}
            spirit_cap = float(runtime.get("精神上限") or attrs["精神上限"] or 1.0)
            health_cap = float(runtime.get("血气上限") or attrs["血气上限"] or 1.0)
            spirit_left.append(float(side_data.get("spirit") or 0) / max(spirit_cap, 1.0))
            health_left.append(float(side_data.get("health") or 0) / max(health_cap, 1.0))
            caps_seen.add((round(health_cap, 1), round(spirit_cap, 1)))
        if fight_unresolved(raw):
            unresolved += 1

    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"战斗体统计：{root}\n")
    out.write(f"样本 {total} 场；行动上限 {args.limit}；等级 {args.等级 or '陪练配置'}\n")
    out.write(
        "属性 "
        + " / ".join(f"{k} {v:g}" for k, v in attrs.items()
                      if k in ("血气上限", "精神上限", "攻击", "防御", "速度",
                               "命中率", "闪避率", "暴击率", "格挡率"))
        + "\n"
    )
    # 构筑里的气机会抬高上限，所以运行时上限才是真值；比值必须拿它当分母。
    for health_cap, spirit_cap in sorted(caps_seen)[:4]:
        out.write(f"  运行时上限：血气 {health_cap:g} · 精神 {spirit_cap:g}\n")
    out.write("\n")

    out.write("—— 时长 ——\n")
    summarize("每场行动数", actions, out)
    out.write(f"  打到行动上限仍未分胜负: {unresolved} / {total}\n\n")

    # 抛错的构筑必须点名，否则内容 bug 会一直被「样本数少了一场」掩盖。
    out.write(f"—— 战斗抛错 {len(failures)} 场 ——\n")
    for line in failures[:40]:
        out.write(f"  {line}\n")
    if not failures:
        out.write("  无\n")
    out.write("\n")

    out.write("—— 伤害 ——\n")
    summarize("单次造成伤害", dealt, out)
    if dealt:
        # 分母用运行时血上限（hp_pool 是双方之和），不能用模块里的陪练基准值
        # ——后者在满构筑/高等级下偏小，会算出一个偏大的「几下打死」。
        out.write(f"  按平均单次伤害算，打死一个人要约 "
                  f"{hp_pool / 2 / statistics.mean(dealt):.1f} 下\n")
    summarize("总伤害 / 双方血上限之和", ratios, out, unit=" 倍")
    out.write(f"  换算成百分比: 中位 {statistics.median(ratios) * 100:.1f}%\n\n")

    out.write("—— 资源 ——\n")
    summarize("终局精神余量占上限比", spirit_left, out)
    summarize("终局血气余量占上限比", health_left, out)
    out.write(f"  每场技能施放次数（全样本）: 中位 {statistics.median(skills):.0f}"
              f" · 均值 {statistics.mean(skills):.1f}\n")
    out.write("  注：真意与器律没有主动技能，中位为 0 是被它们拉下来的，按方向看才有意义\n\n")

    out.write("—— 判定实际发生率 ——\n")
    def rate(done: str, rolled: str) -> None:
        rolled_count = counts[rolled]
        if not rolled_count:
            out.write(f"  {done}: 无样本\n")
            return
        out.write(f"  {done}: {counts[done] / rolled_count * 100:.1f}%"
                  f"（{counts[done]}/{rolled_count}）\n")

    rate("命中后", "命中判定前")
    rate("闪避后", "命中判定前")
    rate("暴击后", "暴击判定前")
    rate("格挡后", "格挡判定前")
    out.write("\n—— 事件总量前 12 ——\n")
    for kind, value in counts.most_common(12):
        out.write(f"  {value:>7}  {kind}\n")
    out.flush()
    core.database.close()

    print(f"样本 {total} 场；详见 {args.report}")
    return 0


def counts_of(events, kind: str) -> int:
    return sum(1 for event in events if event.get("kind") == kind)


if __name__ == "__main__":
    sys.exit(main())
