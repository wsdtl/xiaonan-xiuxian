"""交叉对局对照：两侧装**不同**的卡，补上镜像语料的盲区。

`语料对照.py` 是镜像局（同一张卡两边都装），因此「读自身」与「读对方」在它眼里完全等价——
第三条轴要动的正是这一类。本工具让两侧装不同的卡：每张卡分别对上三名固定对手
（功法 / 真意 / 器律 各一），收益是**来源、属性、目标**这些只在双方不同时才显形的差异终于可测。

    .venv/Scripts/python.exe -X utf8 tools/交叉对局对照.py            # 与入库基准对照
    .venv/Scripts/python.exe -X utf8 tools/交叉对局对照.py --写基准    # 重新取基准

摘要口径与 `语料对照.py` 一致：事件骨架 + 抹掉状态名后的双方状态 + 胜负，取 16 位哈希。

**退出码：0 = 一致，1 = 有差异，2 = 有抛错或基准缺失。**
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import dataclasses
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatRequest,
    CombatantSpec,
)

DEFAULT_BASELINE = ROOT / "tools" / "基准" / "交叉对局摘要.sem"
DATA = ROOT / "data"
ATTRS = {
    "血气上限": 1200, "精神上限": 400, "攻击": 150, "防御": 60, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 0, "伤害减免": 0,
}
SURFACES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("器律", "炼器/内容/器律-*.json"),
)
#: 三名固定对手（每个体裁取一张），保证两侧不同、且覆盖不同体裁。
OPPONENTS = (("功法", "400503"), ("真意", "410275"), ("器律", "700001"))


#: 右方用另一套属性块。**两侧属性必须不同**，否则「读自身属性」与「读目标属性」数值相同，
#: 第三条轴的改动照样不可见——盲区的真正原因是双方属性相同，不只是卡片相同。
ATTRS_R = {
    **ATTRS,
    "血气上限": 1800, "精神上限": 620, "攻击": 90, "防御": 130, "速度": 80,
    "格挡率": 25, "暴击率": 5,
}


def spec(pid: str, section: str, cid: str, *, right: bool = False) -> CombatantSpec:
    return CombatantSpec(
        id=pid, name=pid, attributes=dict(ATTRS_R if right else ATTRS),
        build=(CombatBuildRef(section, cid, instance_id=f"{pid}:{cid}", born_order=0),),
    )


def blind(side: dict) -> dict:
    masked = copy.deepcopy(side)
    for status in masked.get("statuses") or ():
        if isinstance(status, dict) and "name" in status:
            status["name"] = "*"
    return masked


def semantic(raw: dict) -> str:
    skeleton = [
        (e.get("turn"), e.get("kind"), e.get("source_id"), e.get("target_id"),
         round(float(e.get("amount") or 0), 3))
        for e in (raw.get("events") or ())
    ]
    sides = {side: blind(raw.get(side) or {}) for side in ("left", "right")}
    return hashlib.sha256(
        json.dumps([skeleton, sides, raw.get("outcome")], ensure_ascii=False,
                   sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--基准", default=str(DEFAULT_BASELINE))
    parser.add_argument("--写基准", action="store_true")
    parser.add_argument("--数据", default=str(DATA))
    parser.add_argument("--差异名单", default="",
                        help="把完整差异清单写到这个文件（大批次逐条验收用）")
    args = parser.parse_args()
    data_dir = pathlib.Path(args.数据).resolve()

    core = build_game_services(data_dir=data_dir).core
    sem: dict[str, str] = {}
    failures: list[str] = []
    for section, pattern in SURFACES:
        for path in sorted(data_dir.glob(pattern)):
            for entry in json.loads(path.read_text(encoding="utf-8")):
                cid = str(entry["编号"])
                for opponent_section, opponent_id in OPPONENTS:
                    key = f"{section}:{cid} vs {opponent_section}:{opponent_id}"
                    try:
                        result = asyncio.run(core.combat.execute(CombatRequest(
                            left_team=(spec("L", section, cid),),
                            right_team=(spec("R", opponent_section, opponent_id, right=True),),
                            seed=20260911, action_limit=60,
                        )))
                        sem[key] = semantic(dataclasses.asdict(result))
                    except Exception as exc:  # noqa: BLE001
                        sem[key] = f"错误: {type(exc).__name__}: {exc}"
                        failures.append(f"{key}\t{type(exc).__name__}: {exc}")
    core.database.close()

    print(f"{len(sem)} 条，失败 {len(failures)} 条；数据目录 {data_dir}")
    for line in failures[:10]:
        print("  抛错 " + line)

    if args.写基准:
        if failures:
            print("有抛错，拒绝写基准。")
            return 2
        DEFAULT_BASELINE.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_BASELINE.write_text(
            json.dumps(sem, ensure_ascii=False, sort_keys=True, indent=0) + "\n",
            encoding="utf-8",
        )
        print(f"已写入 {DEFAULT_BASELINE}")
        return 0

    baseline = pathlib.Path(args.基准)
    if not baseline.is_file():
        print(f"基准不存在：{baseline}；先跑一次 --写基准")
        return 2
    expected = json.loads(baseline.read_text(encoding="utf-8"))
    changed = sorted(k for k in sem if k in expected and expected[k] != sem[k])
    added = sorted(k for k in sem if k not in expected)
    removed = sorted(k for k in expected if k not in sem)
    print(f"对照 {baseline}（{len(expected)} 条）：差异 {len(changed)} · 新增 {len(added)} · 缺失 {len(removed)}")
    for key in changed[:20]:
        print(f"  [差异] {key}")
    if args.差异名单:
        listing = pathlib.Path(args.差异名单)
        listing.parent.mkdir(parents=True, exist_ok=True)
        # 差异条目的左方就是被改的构筑卡（`功法:400001 vs 真意:700001`），
        # 顺手把左方卡片集去重列出，大批次验收时能一眼核「差异 ⊆ 授权集」。
        left = sorted({key.split(" vs ")[0] for key in changed})
        listing.write_text(
            json.dumps(
                {"差异": changed, "差异卡": left, "新增": added, "缺失": removed},
                ensure_ascii=False, indent=1,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"  完整差异清单已写入 {listing}（涉及左方卡片 {len(left)} 张）")
    return 1 if (changed or added or removed or failures) else 0


if __name__ == "__main__":
    raise SystemExit(main())
