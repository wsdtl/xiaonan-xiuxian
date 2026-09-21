"""战报展示审查：跑一场真实战斗，核对展示对象与战报本身是否自洽。

第 86 轮前，`static/battle-report` 有两处长期没人管的问题，都是「看着有数据、
其实说的是另一回事」，而且**只在多单位编组时才看得出来**（1v1 恰好都对）：

1. **阵营写死成「下标 0 是左方，其余是右方」**。战报标题（同一次战斗）写的是
   「青岚剑修、云岫道人、孤敌悬赏、孤敌悬赏 对阵 黑水魔修、赤炎散人、霜岭客」，
   而展示层把第二个修士和召唤物全画到了敌方——**页面自己跟自己打架**。
   宗门战、讨伐这种多单位编组一直是错的。
2. **简要模式（默认视图）印的是引擎的内部阶段名**：`命中后`、`造成伤害后`、
   `资源消耗后`……一条数字都没有。实测 160 条紧凑事件里 137 条短于 7 个字。
   同一份数据里本来就有 `实际伤害`、`精神 16` 这些事实，只是没带出来。

所以这条审查跑一场战斗，对着**可执行结构**判六件事：

- 展示层的阵营分组与战报的 `阵营` / 标题一致（不多不少，正好两方）；
- 每个参战者的 `team_label` 是他那一方的单位构成（同方一致，不写单个单位的标题）；
- 简要行的文本非空，且**不是把事件类型抄一遍**；
- 事件明细里不出现引擎的内部记账标签与内部编号（`L1`、`L1:战斗对象:1`）；
- 展示载荷里的事件**只带协议声明的字段**（`协议.事件字段` / `协议.事实字段`），
  且事件的来源/目标是**角色键**、能在演员表与调色板里查到（第 115、116 轮）；
- 载荷级的**演员表与调色板**跟战报自己写的参战者一致，并覆盖时间线条上引用的每个角色。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查战报展示.py

**退出码：0 = 干净，1 = 有违规。**
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatReportSpec,
    CombatRequest,
    CombatantSpec,
)

#: 一场足够复杂的战斗：左二右三，各自带功法 / 真意 / 气机 / 器律，能出召唤物与控制状态。
SURFACES = (
    ("功法", 4, "战斗/内容/功法/功法-*.json"),
    ("真意", 3, "战斗/内容/真意/真意-*.json"),
    ("气机", 3, "战斗/内容/气机/气机-*.json"),
    ("器律", 2, "物品/炼器/内容/器律-*.json"),
)
ATTRIBUTES = {
    "血气上限": 1200, "精神上限": 400, "攻击": 150, "防御": 60, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 100, "伤害减免": 0,
}
#: 引擎的内部编号：`L2`、`R1`、`L1:战斗对象:1`。
INTERNAL_ID = re.compile(r"(^|[^0-9A-Za-z])([LR]\d+|\w+:\w+:\d+)([^0-9A-Za-z]|$)")


def _cards(surface: str, count: int, pattern: str) -> list[str]:
    ids: list[str] = []
    for path in sorted((ROOT / "data").glob(pattern)):
        if len(ids) >= count:
            break
        for entry in json.loads(path.read_text(encoding="utf-8")):
            if len(ids) >= count:
                break
            ids.append(str(entry["编号"]))
    return ids


def _combatant(slot: str, name: str, build: list[tuple[str, str]], speed: float) -> CombatantSpec:
    """编号与名字必须不同：判据要查「内部编号有没有漏进战报」，
    拿编号当名字的探针会把自己的编号认成泄漏（第一版就是这么误报的）。"""

    return CombatantSpec(
        id=slot,
        name=name,
        attributes={**ATTRIBUTES, "速度": speed},
        level=5,
        build=tuple(
            CombatBuildRef(section, cid, instance_id=f"{slot}:{section}:{cid}", born_order=index)
            for index, (section, cid) in enumerate(build)
        ),
    )


def _run() -> tuple[dict, dict]:
    cards = {surface: _cards(surface, count, pattern) for surface, count, pattern in SURFACES}
    core = build_game_services().core
    try:
        result = asyncio.run(
            core.combat.execute(
                CombatRequest(
                    left_team=(
                        _combatant("L1", "青岚剑修", [("功法", cards["功法"][0]), ("真意", cards["真意"][0]), ("气机", cards["气机"][0])], 120),
                        _combatant("L2", "云岫道人", [("功法", cards["功法"][1]), ("器律", cards["器律"][0])], 105),
                    ),
                    right_team=(
                        _combatant("R1", "黑水魔修", [("功法", cards["功法"][2]), ("真意", cards["真意"][1]), ("气机", cards["气机"][1])], 110),
                        _combatant("R2", "赤炎散人", [("功法", cards["功法"][3]), ("气机", cards["气机"][2])], 100),
                        _combatant("R3", "霜岭客", [("器律", cards["器律"][1]), ("真意", cards["真意"][2])], 95),
                    ),
                    seed=20260911,
                    action_limit=40,
                    report=CombatReportSpec(
                        scene="演武台",
                        generated_at="2026-01-01T08:30:00+08:00",
                        include_presentation=True,
                    ),
                )
            )
        )
    finally:
        core.database.close()
    main, bundle = result.presentation
    return result.report, {"main": main, "bundle": bundle}


def check_teams(report: dict, presentation: dict) -> list[str]:
    """阵营分组必须与战报自己写的一致。"""

    problems: list[str] = []
    sides = {value["id"]: value["side"] for value in report["participants"]}
    records = presentation["bundle"]["segments"]["0"]["segment"]["final_participants"]
    by_id = {value["key"]: value for value in records}
    for key, side in sides.items():
        record = by_id.get(key)
        if record is None:
            problems.append(f"展示里缺了参战者：{key}")
            continue
        if record["team_id"] != f"team.{side}":
            problems.append(
                f"{record['label']} 在战报里属于 {side}，展示里却挂在 {record['team_id']}"
            )
    teams = {value["team_id"] for value in records}
    if len(teams) != 2:
        problems.append(f"展示把参战者分成了 {len(teams)} 方：" + "、".join(sorted(teams)))
    for team in teams:
        members = [value for value in records if value["team_id"] == team]
        labels = {value["team_label"] for value in members}
        if len(labels) != 1:
            problems.append(f"{team} 一方的队名不统一：{'、'.join(sorted(labels))}")
    return problems


def check_matchup_matches_headline(report: dict, presentation: dict) -> list[str]:
    """对阵条的每一方，名字要跟标题里那一方对得上。

    比的是**集合**不是顺序：标题按引擎的结算顺序取名，展示按参战者顺序取名，
    召唤物入场之后两者未必同序——按顺序比会变成一条动不动就红的判据。
    第一版写的是「any(名字对得上任意一方)」，于是把标题两方对调它也通过
    （反向验证抓出来的：判定太松）。
    """

    title = str(report["headline"])
    left, _, right = title.partition(" 对阵 ")
    records = presentation["bundle"]["segments"]["0"]["segment"]["final_participants"]
    grouped: dict[str, list[str]] = {}
    for value in records:
        grouped.setdefault(value["team_id"], []).append(value["label"])
    problems = []
    for team_id, side, expected in (
        ("team.left", "标题左方", left),
        ("team.right", "标题右方", right),
    ):
        names = sorted(grouped.get(team_id, []))
        if names != sorted(expected.split("、")):
            problems.append(f"{side}是「{expected}」，展示里是「{'、'.join(names)}」")
    return problems


def check_compact_lines(report: dict, presentation: dict) -> list[str]:
    """简要行不能是内部阶段名，也不能是空的。"""

    problems: list[str] = []
    for segment in presentation["bundle"]["segments"].values():
        for entry in segment["segment"]["timeline"]:
            for event in entry["summary_events"]:
                text = str(event.get("text") or "").strip()
                if not text:
                    problems.append(f"简要行是空的：{event.get('label')}")
                elif text == str(event.get("kind") or ""):
                    problems.append(f"简要行把事件类型抄了一遍：{text}")
    return problems


def check_internal_details(report: dict, presentation: dict) -> list[str]:
    """明细里不许出现引擎的内部记账标签与内部编号。

    名单取自 `data/战斗/展示/战报.json`（`标准化.内部明细`），判据不另抄一份：
    抄一份就会出现「数据里加了、判据没加」的缝。
    """

    declared = json.loads(
        (ROOT / "data" / "战斗" / "展示" / "战报.json").read_text(encoding="utf-8")
    )
    kinds = {str(value) for value in declared["标准化"]["内部明细"]}
    problems: list[str] = []
    for events in presentation["bundle"]["events"].values():
        for entry in events["timeline"]:
            for event in entry["events"]:
                for fact in event.get("facts") or ():
                    label = str(fact.get("label") or "")
                    display = str(fact.get("display") or "")
                    if label in kinds:
                        problems.append(f"{event['label']} 的明细里带着内部记账字段：{label}")
                    if INTERNAL_ID.search(display):
                        problems.append(f"{event['label']} 的 {label} 显示了内部编号：{display}")
    return problems


def _events_in(payload) -> list[dict]:
    """把载荷里的事件捞出来：带 `kind` 与 `facts` 的字典就是一条公开事件。"""

    found: list[dict] = []
    if isinstance(payload, dict):
        if "kind" in payload and "facts" in payload:
            found.append(payload)
        for value in payload.values():
            found.extend(_events_in(value))
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            found.extend(_events_in(value))
    return found


def check_event_fields(report: dict, presentation: dict) -> list[str]:
    """展示事件与事实只许带协议声明的字段（名单在 `战报.json` 的 `协议` 里，不另抄一份）。

    事件的来源与目标**是键（字符串），不是小字典**：名字与颜色由载荷级的演员表与调色板
    各发一份，页面查表（第 116 轮）。所以这里顺带核「键能不能查到」。
    """

    declared = json.loads(
        (ROOT / "data" / "战斗" / "展示" / "战报.json").read_text(encoding="utf-8")
    )
    event_fields = {str(value) for value in declared["协议"]["事件字段"]}
    fact_fields = {str(value) for value in declared["协议"]["事实字段"]}
    actors = dict(presentation["main"].get("actors") or {})
    palette = dict(presentation["main"].get("palette") or {})
    events = _events_in(presentation)
    problems: list[str] = []
    if not events:
        return ["展示载荷里一条事件都没有，这条判据没验到东西"]
    for event in events:
        extra = set(event) - event_fields
        missing = event_fields - set(event)
        if extra:
            problems.append(f"{event.get('label')} 多了字段：" + "、".join(sorted(extra)))
        if missing:
            problems.append(f"{event.get('label')} 少了字段：" + "、".join(sorted(missing)))
        for field in ("source", "target"):
            key = event.get(field)
            if not isinstance(key, str) or not key:
                problems.append(f"{event.get('label')} 的 {field} 不是角色键：{key!r}")
            elif key not in actors:
                problems.append(f"{event.get('label')} 的 {field} 不在演员表里：{key}")
        if isinstance(event.get("source"), str) and event["source"] not in palette:
            problems.append(f"{event.get('label')} 的来源不在调色板里：{event['source']}")
        for fact in event.get("facts") or ():
            if set(fact) != fact_fields:
                problems.append(
                    f"{event.get('label')} 的事实字段不符："
                    + "、".join(sorted(str(key) for key in fact))
                )
    return problems


def check_actor_tables(report: dict, presentation: dict) -> list[str]:
    """演员表与调色板要跟战报自己写的参战者一致，且覆盖时间线条上引用的每一个角色。"""

    main = presentation["main"]
    bundle = presentation["bundle"]
    problems: list[str] = []
    for 名, 块 in (("战报头", main), ("明细包", bundle)):
        actors = dict(块.get("actors") or {})
        palette = dict(块.get("palette") or {})
        if not actors or not palette:
            problems.append(f"{名}缺演员表或调色板")
            continue
        for value in report.get("participants") or ():
            键 = str(value["id"])
            if actors.get(键) != str(value["name"]):
                problems.append(f"{名}的演员表与战报不一致：{键} → {actors.get(键)!r}")
            visual = palette.get(键) or {}
            if visual.get("key") != 键 or not visual.get("color") or not visual.get("foreground"):
                problems.append(f"{名}的调色板缺角色颜色：{键}")
        if actors.get("system") != str((report.get("system") or {}).get("name") or ""):
            problems.append(f"{名}的演员表缺系统名（system）")
        if (palette.get("system") or {}).get("key") != "system":
            problems.append(f"{名}的调色板缺系统色（system）")
    for 条 in _timeline_entries(presentation):
        actor = 条.get("actor")
        if actor is None:
            continue
        if actor not in (main.get("actors") or {}):
            problems.append(f"时间线条上的角色不在演员表里：{actor}")
        if actor not in (main.get("palette") or {}):
            problems.append(f"时间线条上的角色不在调色板里：{actor}")
    return problems


def _timeline_entries(payload) -> list[dict]:
    """把时间线条条目捞出来：带 `sequence` 与 `title` 的字典就是一条。"""

    found: list[dict] = []
    if isinstance(payload, dict):
        if "sequence" in payload and "title" in payload:
            found.append(payload)
        for value in payload.values():
            found.extend(_timeline_entries(value))
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            found.extend(_timeline_entries(value))
    return found


CHECKS = (
    ("阵营分组", check_teams),
    ("对阵与标题一致", check_matchup_matches_headline),
    ("简要行", check_compact_lines),
    ("内部明细", check_internal_details),
    ("展示字段", check_event_fields),
    ("角色表一致", check_actor_tables),
)


def main() -> int:
    report, presentation = _run()
    failed: list[str] = []
    for name, check in CHECKS:
        try:
            problems = check(report, presentation)
        except Exception as exc:  # noqa: BLE001
            problems = [f"{type(exc).__name__}: {exc}"]
        for problem in problems:
            print(f"  [{name}] {problem}")
        failed.extend(problems)
    if failed:
        print(f"战报展示违规 {len(failed)} 处")
        return 1
    print(f"战报展示审查通过：{len(CHECKS)} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
