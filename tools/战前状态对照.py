"""战前状态（战丹 / 长期伤势）的终局对照。

`tools/语料对照.py` 只覆盖构筑：功法、真意、器律都走 `CombatBuildRef`。战丹和长期
伤势走的是 `CombatantSpec.prepared_statuses`，通道完全不同，**那条路上的改动它一场
都测不到**——`清惰性节点.py` 就是在这里留下过盲区（368 个节点、64 个整条监听被摘空）。

本工具补上这一半：每枚战丹 / 每条带监听的伤势各配一场真实战斗，
比「outcome + 双方血气/精神/护盾」。

    .venv/Scripts/python.exe -u tools/战前状态对照.py "<改动前的 data 目录>"

判定方式同 `语料对照.py`：**纯改名、纯结构等价应当是 100% 一致**。某一条变成
`None` 说明它在改后数据里已经不存在了（例如整条监听被摘空），要单独看。
"""

from __future__ import annotations

import asyncio
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
    CombatantSpec,
    CombatRequest,
    CombatStatusSpec,
)

#: 陪练卡：任选一张自带主动与被动的功法，两侧都装，好让战前状态的监听有机会触发。
CARD = "400541"
ATTRS = {
    "血气上限": 1200, "精神上限": 400, "攻击": 150, "防御": 60, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 0, "伤害减免": 0,
}


def specs(core, root: pathlib.Path):
    """产出 (标签, CombatStatusSpec)；没带监听的不进战斗。"""

    for path in sorted(root.glob("炼丹/内容/丹药/战丹/*.json")):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            if not (entry.get("使用效果") or {}).get("监听"):
                continue
            medicine = core.medicine.battle(entry["编号"], "01")
            yield f"丹:{entry['编号']}", core.medicine.prepared_status(medicine)

    injuries = root / "角色" / "内容" / "伤势.json"
    if not injuries.exists():
        return
    for entry in json.loads(injuries.read_text(encoding="utf-8")):
        raw = entry.get("战斗状态") or {}
        if not raw.get("监听"):
            continue
        yield f"伤:{entry['编号']}", CombatStatusSpec(
            name=entry["名称"],
            category=raw["类别"],
            remaining_actions=raw["剩余行动"],
            duration_unit=raw["持续单位"],
            modifiers=tuple(
                (str(key), float(value)) for key, value in (raw.get("属性") or {}).items()
            ),
            tags=tuple(raw.get("标签") or ()),
            listeners=tuple(dict(node) for node in raw["监听"]),
            source=entry["编号"],
            source_name=entry["名称"],
            action_limits=tuple(raw.get("行动限制") or ()),
        )


def run(root: pathlib.Path) -> dict[str, str]:
    core = build_game_services(data_dir=root).core
    result: dict[str, str] = {}
    for label, prepared in specs(core, root):
        def side(pid: str) -> CombatantSpec:
            return CombatantSpec(
                id=pid, name=pid, attributes=dict(ATTRS),
                build=(CombatBuildRef(
                    "功法", CARD, instance_id=f"{pid}:{CARD}", born_order=0),),
                prepared_statuses=(prepared,),
            )

        try:
            raw = dataclasses.asdict(asyncio.run(core.combat.execute(CombatRequest(
                left_team=(side("L"),), right_team=(side("R"),),
                seed=20260911, action_limit=60,
            ))))
        except Exception as exc:  # noqa: BLE001
            result[label] = f"错误 {type(exc).__name__}"
            continue
        final = {
            s: {k: round(float(raw[s][k]), 3) for k in ("health", "spirit", "shield")}
            for s in ("left", "right")
        }
        result[label] = hashlib.sha256(
            json.dumps([final, raw.get("outcome")], sort_keys=True).encode()
        ).hexdigest()[:16]
    core.database.close()
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: tools/战前状态对照.py <改动前的 data 目录>")
        return 2
    before = run(pathlib.Path(sys.argv[1]))
    after = run(ROOT / "data")
    keys = sorted(set(before) | set(after))
    same = [k for k in keys if before.get(k) == after.get(k)]
    gone = [k for k in keys if k in before and k not in after]
    changed = [k for k in keys if k in after and before.get(k) != after.get(k)]
    print(f"战前状态终局一致 {len(same)} / {len(keys)}")
    if gone:
        print(f"改后不再存在的 {len(gone)} 条（监听被摘空）:")
        for key in gone[:20]:
            print(f"   {key}  （改前摘要 {before[key]}）")
    if changed:
        print(f"终局真变了的 {len(changed)} 条:")
        for key in changed[:20]:
            print(f"   {key}  {before.get(key)} -> {after.get(key)}")
    return 0 if not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
