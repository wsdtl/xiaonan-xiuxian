"""战斗语料跑器：逐卡对战，输出「抹名语义摘要」用于改动前后的对照。

摘要抹掉一切名字，只留 事件种类/来源/目标/数值 与终局资源，所以：

    纯改名、搬位置这类**结构等价**改动 → 摘要应逐条一致（覆盖 1967 张构筑卡：
    功法 600 · 真意 600 · **气机 703** · 器律 64）；
    有差异就是真的改了行为。

    # 生成摘要（默认写到根目录的临时文件，被 .gitignore 忽略）
    .venv/Scripts/python.exe -u tools/语料对照.py _改后

    # 与已入库的基准对照；有差异就非零退出，可以直接当检查用
    .venv/Scripts/python.exe -u tools/语料对照.py --对照 tools/基准/语料摘要.sem

    # 或跑另一份数据目录（改平衡后重新取基准时用）
    $env:CORPUS_DATA = "<另一份 data 目录>"

**它不是平衡的评审。** 平衡改动（`伤害.json` 的闸、卡的数值）会让大票摘要
变化——那时它的用途是「确认变化范围符合预期」，不是「确认没变」。
基准本身是 `tools/基准/语料摘要.sem`（入库跟踪，48 KB），所以换一个会话也能直接对照。
基准只在**零抛错**时才会写：把带错误的运行固化成基准，等于把坏状态当成正确。

## `--摘要 行为`：改「属性基数」这类改动唯一能用的判据

全量摘要带着**参战者快照**，里面有属性的绝对值。所以像「把加成属性的基准从 0 补到 100」
这种**等价改写**，全量摘要会 1967/1967 全变——它证明不了任何事。

`--摘要 行为` 把参战者快照去掉，只留 `事件骨架（时点/种类/来源/目标/数值）+ 终局`：

    .venv/Scripts/python.exe -u tools/语料对照.py --摘要 行为 \
        --对照 tools/基准/语料行为摘要.sem

它逐条相同才说明「伤害数值与胜负一个没动」。改基数、改口径、改名字这类**声称等价**的改动
都该先用它验，再用全量摘要去重取基准。
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import dataclasses
import hashlib
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

parser = argparse.ArgumentParser()
parser.add_argument("输出", nargs="?", default=str(ROOT / "_输出" / "语料.json"),
                    help="摘要写到 <输出>.sem（默认根目录临时文件，不入库）")
parser.add_argument("--对照", dest="对照", default="",
                    help="与这份基准摘要对照；有差异则非零退出")
parser.add_argument("--数据", dest="数据", default="",
                    help="要跑的数据目录；默认 data，或环境变量 CORPUS_DATA")
parser.add_argument("--允许失败", dest="允许失败", action="store_true",
                    help="有战斗抛错时也写摘要；默认拒绝，避免把坏状态当基准")
parser.add_argument("--差异名单", dest="差异名单", default="",
                    help="把完整差异清单写到这个文件（大批次逐条验收用）")
parser.add_argument("--摘要", dest="摘要", choices=("全量", "行为"), default="全量",
                    help="行为＝只摘要事件骨架与终局，去掉参战者快照（改属性基数/口径时用）")
args = parser.parse_args()

out = Path(args.输出)
# 摘要一律写成 `<输出>.sem`。以前传 `tools/基准/语料摘要.json` 会写出
# `语料摘要.json.sem` 这种**野文件**：真正的基准没被刷新，下一批的差异核对就混进上一批的旧差异
# （第 26 轮就这么踩过一次）。所以这里把 `.json` 后缀剥掉，按「基准名」而不是「文件名」理解。
if out.suffix == ".json":
    out = out.with_suffix("")
# 跑语料时的过程输出写日志文件；但**判定结论要回到真终端**，否则「一致 N / 差异 M」
# 会被重定向吞掉，当检查用时看不见。所以先留住真 stdout。
REAL_STDOUT = sys.stdout
(ROOT / "_输出").mkdir(exist_ok=True)
sys.stdout = io.TextIOWrapper(
    open(ROOT / "_输出" / "语料日志.txt", "wb"), encoding="utf-8", write_through=True
)


def report(*values: object) -> None:
    print(*values, file=REAL_STDOUT)

from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatantSpec,
    CombatRequest,
)

DATA_DIR = Path(args.数据 or os.environ.get("CORPUS_DATA") or ROOT / "data").resolve()

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

corpus: list[tuple[str, str]] = []
for section, pattern in SURFACES:
    for path in sorted(DATA_DIR.glob(pattern)):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            corpus.append((section, str(entry["编号"])))

core = build_game_services(data_dir=DATA_DIR).core


def spec(pid: str, section: str, cid: str) -> CombatantSpec:
    return CombatantSpec(
        id=pid, name=pid, attributes=dict(ATTRS),
        build=(CombatBuildRef(section, cid, instance_id=f"{pid}:{cid}", born_order=0),),
    )


def blind(side: dict) -> dict:
    masked = copy.deepcopy(side)
    for status in masked.get("statuses") or ():
        if isinstance(status, dict) and "name" in status:
            status["name"] = "*"
    return masked


def semantic(raw: dict) -> str:
    events = raw.get("events") or ()
    skeleton = [
        (e.get("turn"), e.get("kind"), e.get("source_id"), e.get("target_id"),
         round(float(e.get("amount") or 0), 3))
        for e in events
    ]
    if args.摘要 == "行为":
        # 不带参战者快照：那一块里有属性的绝对值，改基数就会全变，与行为无关。
        payload: list = [skeleton, raw.get("outcome")]
    else:
        sides = {side: blind(raw.get(side) or {}) for side in ("left", "right")}
        payload = [skeleton, sides, raw.get("outcome")]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


sem: dict[str, str] = {}
failures: list[str] = []
for section, cid in corpus:
    key = f"{section}:{cid}"
    try:
        result = asyncio.run(core.combat.execute(CombatRequest(
            left_team=(spec("L", section, cid),),
            right_team=(spec("R", section, cid),),
            seed=20260911, action_limit=60,
        )))
        raw = dataclasses.asdict(result)
        raw.pop("report", None)
        sem[key] = semantic(raw)
    except Exception as exc:  # noqa: BLE001
        sem[key] = f"错误: {type(exc).__name__}: {exc}"
        failures.append(f"{key}\t{type(exc).__name__}: {exc}")

core.database.close()

print(f"{len(sem)} 条，失败 {len(failures)} 条；数据目录 {DATA_DIR}")
for line in failures[:20]:
    print("  抛错 " + line)
report(f"{len(sem)} 条，失败 {len(failures)} 条；数据目录 {DATA_DIR}")

if failures and not args.允许失败:
    report("有战斗抛错，拒绝写摘要（会把坏状态固化成基准）；确有需要加 --允许失败")
    sys.exit(2)

Path(str(out) + ".sem").parent.mkdir(parents=True, exist_ok=True)
Path(str(out) + ".sem").write_text(
    json.dumps(sem, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8"
)
print(f"摘要写入 {out}.sem")

if not args.对照:
    sys.exit(0)

baseline_path = Path(args.对照)
if baseline_path.suffix == ".json":
    baseline_path = baseline_path.with_suffix("")
if not baseline_path.is_absolute():
    baseline_path = (ROOT / baseline_path).resolve()
# 写摘要时会自动补 `.sem`（`<输出>.sem`），所以 `--对照` 也接受不带后缀的写法。
if not baseline_path.exists() and Path(str(baseline_path) + ".sem").exists():
    baseline_path = Path(str(baseline_path) + ".sem")
if not baseline_path.exists():
    report(f"基准不存在：{baseline_path}")
    sys.exit(2)

baseline: dict[str, str] = json.loads(baseline_path.read_text(encoding="utf-8"))
same = [key for key in sem if key in baseline and baseline[key] == sem[key]]
changed = [key for key in sem if key in baseline and baseline[key] != sem[key]]
added = [key for key in sem if key not in baseline]
removed = [key for key in baseline if key not in sem]

report("")
report(f"对照 {baseline_path}（{len(baseline)} 条）")
report(f"  一致 {len(same)} · 差异 {len(changed)} · 新增 {len(added)} · 缺失 {len(removed)}")
for label, keys in (("差异", changed[:40]), ("新增", added[:20]), ("缺失", removed[:20])):
    for key in keys:
        was = baseline.get(key, "（无）")
        report(f"    {label} {key}: {was} -> {sem.get(key, '（无）')}")
if args.差异名单:
    # 大批次（例如全量映射批 640 条）靠截图核不完，把完整清单落盘再逐条比对。
    listing = Path(args.差异名单)
    listing.parent.mkdir(parents=True, exist_ok=True)
    listing.write_text(
        json.dumps(
            {"差异": sorted(changed), "新增": sorted(added), "缺失": sorted(removed)},
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    report(f"   完整差异清单已写入 {listing}")
if len(changed) > 40:
    report(f"    …… 差异共 {len(changed)} 条，只列前 40")

sys.exit(1 if (changed or added or removed) else 0)
