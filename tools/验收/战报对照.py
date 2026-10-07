"""战报的终局对照：每场战斗的战报与战报展示各取一个摘要。

`tools/语料对照.py` 刻意**把战报排除在摘要之外**（见那里的 `raw.pop("report", None)`）：
它的摘要把状态名抹成 `*`，好让词条改名不算行为变化，而战报是长篇措辞，收进去会让那条
通道对改名过敏——排除是对的。代价是 `game/core/combat/report.py`（572 行）与
`presentation.py` 里的战报构造**完全没有判据**：少拼一个字段、少给一个分类、把某类事件
的文案漏掉，战斗语料一场都测不到。

本工具补上这一段：同一套语料、同一批种子，但收的是战报本身。

    # 与入库基准对照（推荐；有差异则非零退出）
    .venv/Scripts/python.exe -X utf8 tools/战报对照.py

    # 重新取基准（改战报措辞或字段之后）
    .venv/Scripts/python.exe -X utf8 tools/战报对照.py --写基准

**`generated_at` 固定传入**：它默认取 `datetime.now()`，不固定就每次都不一样，收成基准
毫无意义。工具开头会先跑一场自检，两次摘要不一致就拒绝继续。

判据看改动性质：**纯结构等价（把战报构造拆成若干段）应当 100% 一致**；改措辞、改字段或
改分类则差异必须恰好是你要改的那批实体。摘要只存每场 16 位哈希（战报单场 16 到 31 万
字符，全文入库不合适），差异会指到具体是哪张卡。

**退出码约定（与另四条通道一致）：0 = 一致，1 = 有差异，2 = 有抛错或基准缺失。**
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import pathlib
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

DEFAULT_BASELINE = ROOT / "tools" / "基准" / "战报摘要.sem"

#: 战报里的时间戳，固定住才谈得上「对照」。
FIXED_GENERATED_AT = "2026-01-01T00:00:00+08:00"

ATTRS = {
    "血气上限": 1200, "精神上限": 400, "攻击": 150, "防御": 60, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    #: 伤害加成是加成口径，基准 100 = 不增不减；写 0 等于把伤害乘成 0。
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 100, "伤害减免": 0,
}
SURFACES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("器律", "物品/炼器/内容/器律-*.json"),
)


def spec(pid: str, section: str, cid: str) -> CombatantSpec:
    return CombatantSpec(
        id=pid, name=pid, attributes=dict(ATTRS),
        build=(CombatBuildRef(section, cid, instance_id=f"{pid}:{cid}", born_order=0),),
    )


def battle_report(core, section: str, cid: str) -> tuple[str, int]:
    """跑一场并返回（战报+展示的摘要, 摘要原文长度）。"""

    result = asyncio.run(
        core.combat.execute(
            CombatRequest(
                left_team=(spec("L", section, cid),),
                right_team=(spec("R", section, cid),),
                seed=20260911,
                action_limit=60,
                report=CombatReportSpec(
                    scene="切磋",
                    generated_at=FIXED_GENERATED_AT,
                    include_presentation=True,
                ),
            )
        )
    )
    raw = dataclasses.asdict(result)
    blob = json.dumps(
        [raw.get("report"), raw.get("presentation")],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16], len(blob)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("输出", nargs="?", help="摘要写到 <输出>.sem")
    parser.add_argument("--对照", help="与这份基准摘要对照；有差异则非零退出")
    parser.add_argument("--数据", help="要跑的数据目录；默认 data，或环境变量 CORPUS_DATA")
    parser.add_argument("--写基准", action="store_true", help="把当前摘要写进入库基准")
    parser.add_argument("--允许失败", action="store_true", help="有战斗抛错时也写摘要")
    parser.add_argument("--差异名单", default="",
                        help="把完整差异清单写到这个文件（大批次逐条验收用；终端只列前 40 条）")
    args = parser.parse_args()

    data_dir = pathlib.Path(
        args.数据 or os.environ.get("CORPUS_DATA") or ROOT / "data"
    ).resolve()
    corpus: list[tuple[str, str]] = []
    for section, pattern in SURFACES:
        for path in sorted(data_dir.glob(pattern)):
            for entry in json.loads(path.read_text(encoding="utf-8")):
                corpus.append((section, str(entry["编号"])))

    core = build_game_services(data_dir=data_dir).core

    # 自检：战报带时间戳，不固定就谈不上对照。先跑一场两次。
    probe_section, probe_id = corpus[0]
    first, _ = battle_report(core, probe_section, probe_id)
    second, size = battle_report(core, probe_section, probe_id)
    if first != second:
        print("战报不是确定性的（同一场两次摘要不同），收成基准没有意义")
        core.database.close()
        return 2
    print(f"自检通过：{probe_section} {probe_id} 两次摘要一致；单场摘要约 {size:,} 字符")

    sem: dict[str, str] = {}
    failures: list[str] = []
    for section, cid in corpus:
        key = f"{section}:{cid}"
        try:
            digest, _ = battle_report(core, section, cid)
            sem[key] = digest
        except Exception as exc:  # noqa: BLE001
            sem[key] = f"错误: {type(exc).__name__}: {exc}"
            failures.append(f"{key}\t{type(exc).__name__}: {exc}")
    core.database.close()

    print(f"{len(sem)} 条，失败 {len(failures)} 条；数据目录 {data_dir}")
    for line in failures[:20]:
        print("  抛错 " + line)

    if failures and not args.允许失败:
        print("有战斗抛错，拒绝写摘要（会把坏状态固化成基准）；确有需要加 --允许失败")
        return 2

    def write(target: pathlib.Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(sem, ensure_ascii=False, sort_keys=True, indent=0) + "\n",
            encoding="utf-8",
        )

    # 不明确要求就**绝不写盘**：无参数运行是「与入库基准对照」，不能顺手把基准覆盖掉。
    if args.写基准:
        write(DEFAULT_BASELINE)
        print(f"已写入 {DEFAULT_BASELINE}")
        return 0
    if args.输出:
        target = pathlib.Path(str(args.输出) + ".sem")
        write(target)
        print(f"已写入 {target}")
        return 0

    baseline = pathlib.Path(args.对照) if args.对照 else DEFAULT_BASELINE
    if not baseline.is_file():
        print(f"基准不存在：{baseline}")
        return 2
    try:
        expected = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"基准无法读取：{exc}")
        return 2

    same = [key for key in sem if expected.get(key) == sem[key]]
    changed = [key for key in sem if key in expected and expected[key] != sem[key]]
    added = [key for key in sem if key not in expected]
    removed = [key for key in expected if key not in sem]
    print(f"对照 {baseline}（{len(expected)} 条）")
    print(f"  一致 {len(same)} · 差异 {len(changed)} · 新增 {len(added)} · 缺失 {len(removed)}")
    for key in changed[:40]:
        print(f"    {key}: {expected[key]} -> {sem[key]}")
    if len(changed) > 40:
        print(f"    …… 差异共 {len(changed)} 条，只列前 40")
    if args.差异名单:
        listing = pathlib.Path(args.差异名单)
        listing.parent.mkdir(parents=True, exist_ok=True)
        # 键是 `体裁:编号`，顺手把左方卡片去重列出，大批次一眼核「差异 ⊆ 授权集」。
        cards = sorted({":".join(key.split(":")[:2]) for key in changed if ":" in key})
        listing.write_text(
            json.dumps({"差异": changed, "差异卡": cards, "新增": added, "缺失": removed},
                       ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        print(f"    完整差异清单已写入 {listing}（{len(changed)} 条）")
    for key in added[:20]:
        print(f"    新增 {key}")
    for key in removed[:20]:
        print(f"    缺失 {key}")
    if changed or added or removed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
