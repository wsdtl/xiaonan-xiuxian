"""战斗语料跑器：逐卡对战，输出「抹名语义摘要」用于改动前后的对照。

摘要抹掉一切名字，只留 事件种类/来源/目标/数值 与终局资源，所以：
**纯改名改动应当 1264/1264 一致；有差异就是真的改了行为。**

    .venv/Scripts/python.exe -u tools/语料对照.py _改前
    # 改动后
    .venv/Scripts/python.exe -u tools/语料对照.py _改后
    # 或直接跑另一份数据目录做对照
    $env:CORPUS_DATA = "<另一份 data 目录>"
"""

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

out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "_语料.json")
sys.stdout = io.TextIOWrapper(open(ROOT / "_语料日志.txt", "wb"), encoding="utf-8", write_through=True)

from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatantSpec,
    CombatRequest,
)

DATA_DIR = Path(os.environ.get("CORPUS_DATA", ROOT / "data")).resolve()

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
    sides = {side: blind(raw.get(side) or {}) for side in ("left", "right")}
    return hashlib.sha256(
        json.dumps([skeleton, sides, raw.get("outcome")], ensure_ascii=False,
                   sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


sem: dict[str, str] = {}
failures = 0
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
        failures += 1

Path(str(out) + ".sem").write_text(
    json.dumps(sem, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8"
)
print(f"{out}: {len(sem)} 条，失败 {failures} 条；数据目录 {DATA_DIR}")
