"""战场环境的终局对照：把全部战场环境各跑一场真实战斗，做成可比对的摘要。

## 为什么需要它

`tools/语料对照.py` 只跑**构筑**（功法/真意/气机/器律都走 `CombatBuildRef`），
`tools/战前状态对照.py` 只跑**战丹与长期伤势**。战场环境两边都不在：实测全仓
`tools/` 下**没有任何一处构造 `CombatFieldSpec`**——那 55 个环境、以及它们 `阶段`
里的 `入阶能力 / 常驻能力`，行为上一直是零覆盖。

数据侧的空缺由架构审查兜（`tools/构筑模板.py` 判据 + `restore_reference` 的逐字节
回环），但「环境能不能真的进战斗」只有跑一遍才知道。

## 判据

对每个环境跑同一场战斗（同种子、同双方配置），摘要收：

- `阶段`：战斗结束时的 `stage_index / stage_name`——环境真的生效时，承伤推进会抬阶；
- `结局`：胜方 / 行动数；
- `双方`：终局血气、精神、护盾。

种子固定，所以摘要应当完全可复现。**差异要么是你打算改的那批环境，要么是回归。**

另外单独报一行体检：**有多少环境的 `入阶/常驻能力` 真的被评估过**（`触发次数 > 0`）。
环境完全不生效时（例如加载期没展开、能力被丢掉）会全部是 0，那是比逐条差异更早的警报。

抬阶（`阶段 >= 1`）也一并报，但**不作为判据**：环境若让战斗很快结束（实测 `无相境`
3 个动作就打完了），承伤推进不到抬阶线是正常的，不是缺陷。

## 用法

```powershell
.venv/Scripts/python.exe -X utf8 tools/战场环境对照.py          # 与入库基准对照
.venv/Scripts/python.exe -X utf8 tools/战场环境对照.py --写基准  # 更新基准
```

**退出码约定（与另三条语料通道一致）：0 = 一致，1 = 有差异，2 = 有抛错或基准缺失。**
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatFieldSpec,
    CombatantSpec,
    CombatRequest,
)

DEFAULT_BASELINE = ROOT / "tools" / "基准" / "战场环境摘要.json"

#: 陪练卡：自带主动与被动的功法，两侧都装，好让环境阶段有伤害推进。
CARD = "400541"
SEED = 20260913
ACTION_LIMIT = 200

#: 双方属性。血气刻意给大：环境的阶段按「累计承伤 / 血气基准」推进，
#: 血太少会在跑到二阶之前就结束战斗。
ATTRS = {
    "血气上限": 2600, "精神上限": 900, "攻击": 300, "防御": 50, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    #: 伤害加成是加成口径，基准 100 = 不增不减；写 0 等于把伤害乘成 0。
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 100, "伤害减免": 0,
}


def _side(pid: str) -> CombatantSpec:
    return CombatantSpec(
        id=pid,
        name=pid,
        attributes=dict(ATTRS),
        build=(
            CombatBuildRef("功法", CARD, instance_id=f"{pid}:{CARD}", born_order=0),
        ),
    )


def digest(root: pathlib.Path) -> tuple[dict[str, object], list[str]]:
    """返回（摘要, 抛错清单）。抛错要记账：当成空结果会掩盖最该看见的回归。"""

    services = build_game_services(data_dir=root)
    core = services.core
    environments = sorted(core.combat._require_engine().catalog.environments)
    summary: dict[str, object] = {}
    failures: list[str] = []
    try:
        for environment_id in environments:
            try:
                result = asyncio.run(core.combat.execute(CombatRequest(
                    left_team=(_side("L"),),
                    right_team=(_side("R"),),
                    seed=SEED,
                    action_limit=ACTION_LIMIT,
                    field=CombatFieldSpec(
                        environment_id=environment_id,
                        origin="地表",
                        scene="对照",
                        xy=(1, 1),
                        altitude=100,
                        terrain="平原",
                    ),
                )))
            except Exception as exc:  # noqa: BLE001 - 任何异常都要变成可见的失败
                failures.append(f"{environment_id}：{type(exc).__name__}: {exc}")
                continue
            field = result.field
            summary[environment_id] = {
                "名称": field.name if field is not None else "",
                # 阶段推进是「环境真的生效」最直接的证据：按承伤比例抬阶。
                "阶段": [field.stage_index, field.stage_name] if field is not None else [],
                # 触发计数：环境阶段里的入阶/常驻能力被评估了多少次。
                "触发次数": result.trigger_activations,
                "行动数": result.actions,
                "双方": {
                    side: [
                        round(float(value.health), 3),
                        round(float(value.spirit), 3),
                        round(float(value.shield), 3),
                    ]
                    for side, value in (("左", result.left), ("右", result.right))
                },
            }
    finally:
        core.database.close()
    return summary, failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--基准", default=str(DEFAULT_BASELINE), help="入库基准摘要")
    parser.add_argument("--写基准", action="store_true", help="把当前摘要写进 --基准")
    parser.add_argument("--数据", default=str(ROOT / "data"), help="要跑的数据目录")
    args = parser.parse_args()

    root = pathlib.Path(args.数据)
    summary, failures = digest(root)
    print(f"{len(summary)} 个环境，抛错 {len(failures)} 个；数据目录 {root}")
    for failure in failures:
        print(f"  {failure}")

    fired = [key for key, value in summary.items() if (value.get("触发次数") or 0) > 0]
    advanced = [key for key, value in summary.items() if (value.get("阶段") or [0])[0] >= 1]
    print(f"  环境能力被评估过的：{len(fired)} / {len(summary)}"
          + ("（一个都没触发，环境很可能完全没生效）" if summary and not fired else ""))
    print(f"  其中推进到二阶以上的：{len(advanced)} / {len(summary)}"
          "（不抬阶不代表缺陷：战斗太快结束时承伤推进不到抬阶线）")

    baseline = pathlib.Path(args.基准)
    if args.写基准:
        if failures:
            print("有环境抛错，拒绝写基准——否则会把坏状态固化成判据。")
            return 2
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n",
            encoding="utf-8",
        )
        print(f"已写入 {baseline}")
        return 0

    if not baseline.is_file():
        print(f"基准不存在：{baseline}；先跑一次 --写基准")
        return 2
    try:
        expected = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"基准无法读取：{exc}")
        return 2
    if not isinstance(expected, dict):
        print(f"基准结构不对：{baseline} 应为对象")
        return 2

    changed = sorted(
        key for key in summary.keys() & expected.keys() if summary[key] != expected[key]
    )
    added = sorted(summary.keys() - expected.keys())
    missing = sorted(expected.keys() - summary.keys())
    same = len(summary.keys() & expected.keys()) - len(changed)
    print(
        f"对照 {baseline}（{len(expected)} 条）："
        f"一致 {same} / {len(summary)} · 差异 {len(changed)}"
        f" · 新增 {len(added)} · 缺失 {len(missing)}"
    )
    for key in changed[:20]:
        before = json.dumps(expected[key], ensure_ascii=False, sort_keys=True)
        after = json.dumps(summary[key], ensure_ascii=False, sort_keys=True)
        print(f"  [差异] {key}")
        print(f"      -{before[:160]}")
        print(f"      +{after[:160]}")
    if len(changed) > 20:
        print(f"  …… 其余 {len(changed) - 20} 条差异从略")
    for key in added[:10]:
        print(f"  [新增] {key}")
    for key in missing[:10]:
        print(f"  [缺失] {key}")

    if failures:
        return 2
    return 1 if (changed or added or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
