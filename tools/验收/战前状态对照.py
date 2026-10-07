"""战前状态（战丹 / 长期伤势）的终局对照。

`tools/语料对照.py` 只覆盖构筑：功法、真意、器律都走 `CombatBuildRef`。战丹和长期
伤势走的是 `CombatantSpec.prepared_statuses`，通道完全不同，**那条路上的改动它一场
都测不到**——历史上这里留下过盲区（368 个节点、64 个整条监听被摘空）。

本工具补上这一半：每枚战丹 / 每条带监听的伤势各配一场真实战斗，
比「outcome + 双方血气/精神/护盾」。

    # 与入库基准对照（推荐；有差异则非零退出）
    .venv/Scripts/python.exe -u tools/战前状态对照.py

    # 重新取基准
    .venv/Scripts/python.exe -u tools/战前状态对照.py --写基准

    # 旧用法：直接比改动前的 data 目录
    .venv/Scripts/python.exe -u tools/战前状态对照.py "<改动前的 data 目录>"

判定方式同 `语料对照.py`：**纯改名、纯结构等价应当是 100% 一致**。某一条变成
`None` 说明它在改后数据里已经不存在了（例如整条监听被摘空），要单独看。

基准是 `tools/基准/战前状态摘要.json`（入库跟踪），只在**零抛错**时才会写。
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from 构筑模板展开 import load_build_json as _load_build_json  # noqa: E402
from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatantSpec,
    CombatRequest,
    CombatStatusSpec,
)

DEFAULT_BASELINE = ROOT / "tools" / "基准" / "战前状态摘要.json"

#: 陪练卡：任选一张自带主动与被动的功法，两侧都装，好让战前状态的监听有机会触发。
CARD = "400541"
ATTRS = {
    "血气上限": 1200, "精神上限": 400, "攻击": 150, "防御": 60, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    #: 伤害加成是加成口径，基准 100 = 不增不减；写 0 等于把伤害乘成 0。
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 100, "伤害减免": 0,
}


def specs(core, root: pathlib.Path):
    """产出 (标签, CombatStatusSpec)；没带监听的不进战斗。

    读文件必须走 `_load_build_json`：战丹与长期伤势的监听节点已经模板化，直接
    `json.loads` 拿到的是 `{"模板": …, "参数": …}` 引用，构造 `CombatStatusSpec`
    时会被判成「不是监听事件节点」而整条失败。
    """

    for path in sorted(root.glob("物品/炼丹/内容/丹药/战丹/*.json")):
        for entry in _load_build_json(path):
            if not (entry.get("使用效果") or {}).get("监听"):
                continue
            medicine = core.medicine.battle(entry["编号"], "01")
            yield f"丹:{entry['编号']}", core.medicine.prepared_status(medicine)

    injuries = root / "角色" / "内容" / "伤势.json"
    if not injuries.exists():
        return
    for entry in _load_build_json(injuries):
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


def run(root: pathlib.Path) -> tuple[dict[str, str], list[str]]:
    core = build_game_services(data_dir=root).core
    result: dict[str, str] = {}
    failures: list[str] = []
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
            result[label] = f"错误 {type(exc).__name__}：{exc}"
            failures.append(f"{label}\t{type(exc).__name__}: {exc}")
            continue
        final = {
            s: {k: round(float(raw[s][k]), 3) for k in ("health", "spirit", "shield")}
            for s in ("left", "right")
        }
        result[label] = hashlib.sha256(
            json.dumps([final, raw.get("outcome")], sort_keys=True).encode()
        ).hexdigest()[:16]
    core.database.close()
    return result, failures


def compare(before: dict[str, str], after: dict[str, str], 标题: str) -> int:
    keys = sorted(set(before) | set(after))
    same = [k for k in keys if before.get(k) == after.get(k)]
    gone = [k for k in keys if k in before and k not in after]
    added = [k for k in keys if k in after and k not in before]
    changed = [k for k in keys if k in after and k in before and before.get(k) != after.get(k)]
    print(f"{标题}：一致 {len(same)} / {len(keys)}"
          f" · 差异 {len(changed)} · 新增 {len(added)} · 缺失 {len(gone)}")
    if gone:
        print(f"  改后不再存在的 {len(gone)} 条（监听被摘空）:")
        for key in gone[:20]:
            print(f"    {key}  （改前摘要 {before[key]}）")
    if added:
        print(f"  改后新增的 {len(added)} 条:")
        for key in added[:20]:
            print(f"    {key}  {after[key]}")
    if changed:
        print(f"  终局真变了的 {len(changed)} 条:")
        for key in changed[:20]:
            print(f"    {key}  {before.get(key)} -> {after.get(key)}")
    return 1 if (changed or added or gone) else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("改动前", nargs="?", default="",
                        help="改动前的 data 目录（旧用法；与 --基准 二选一）")
    parser.add_argument("--基准", dest="基准", default=str(DEFAULT_BASELINE),
                        help="入库基准摘要；默认 tools/基准/战前状态摘要.json")
    parser.add_argument("--写基准", dest="写基准", action="store_true",
                        help="把当前数据目录的摘要写进 --基准")
    parser.add_argument("--数据", dest="数据", default="",
                        help="要跑的数据目录；默认仓库的 data")
    args = parser.parse_args()

    data_dir = pathlib.Path(args.数据).resolve() if args.数据 else ROOT / "data"
    after, failures = run(data_dir)
    print(f"{len(after)} 条，失败 {len(failures)} 条；数据目录 {data_dir}")
    for line in failures[:20]:
        print("  抛错 " + line)

    baseline_path = pathlib.Path(args.基准)
    if not baseline_path.is_absolute():
        baseline_path = (ROOT / baseline_path).resolve()

    if args.写基准:
        if failures:
            print("有战斗抛错，拒绝写基准（会把坏状态固化成正确）；先修掉再取")
            return 2
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(
            json.dumps(after, ensure_ascii=False, indent=0, sort_keys=True),
            encoding="utf-8",
        )
        print(f"基准写入 {baseline_path}（{len(after)} 条）")
        return 0

    if args.改动前:
        before, 前失败 = run(pathlib.Path(args.改动前).resolve())
        if 前失败:
            print(f"改动前数据目录有 {len(前失败)} 条抛错，对照结论不可靠")
        return compare(before, after, f"对照改动前目录 {args.改动前}")

    if not baseline_path.exists():
        print(f"基准不存在：{baseline_path}；先跑 --写基准 取一次")
        return 2
    baseline: dict[str, str] = json.loads(baseline_path.read_text(encoding="utf-8"))
    return compare(baseline, after, f"对照 {baseline_path}（{len(baseline)} 条）")


if __name__ == "__main__":
    raise SystemExit(main())
