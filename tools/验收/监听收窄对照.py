"""监听收窄对照：同一批语料跑两条腿，一条走「按阵营收窄候选」，一条走「整张排序表」。

派发一条事件时，引擎不必把整张监听表问一遍：监听自己声明了「观察角色 + 阵营关系」，
所以「自身」的那条只可能在当事人身上、「己方 / 敌方」的只可能在这一侧那几位身上。
`AbilityRuntime._listeners_for` 就按这个把候选收窄，代价是**漏给是静默的**——少问一条
监听 = 少一段结算，战报照旧能出，只有把两条腿摆在一起逐场比才看得见。

漏给的坑真踩过一次（第 112 轮）：`修改事件目标` 会在派发途中把事件目标改掉，改完之后
先前被收窄掉的监听里就有人重新符合条件，而原实现是「每条约在它自己的位次上问一次」，
不会回头补问位次在前的那些。收窄版当时按「目标一变就整表重扫」补，结果**多问**了，
一场真意就多出 30 条事件。现在改成按位次补问（只补位次在后面的），这份判据就是那次
修复留下的护栏。

    # 对照（默认：跑全部四个面的语料，有差异则非零退出）
    .venv/Scripts/python.exe -X utf8 tools/监听收窄对照.py

    # 跑另一份数据目录
    .venv/Scripts/python.exe -X utf8 tools/监听收窄对照.py --数据 <另一份 data>

**退出码：0 = 逐场一致，1 = 有差异。** 摘要口径与 `tools/语料对照.py` 相同
（事件骨架 + 参战者快照 + 终局），所以「一致」是行为一致，不是「事件条数差不多」。
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
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--数据", dest="数据", default="", help="要跑的数据目录；默认 data，或环境变量 CORPUS_DATA")
args = parser.parse_args()

DATA_DIR = Path(args.数据 or os.environ.get("CORPUS_DATA") or ROOT / "data").resolve()

# 过程输出写日志文件，判定结论回到真终端——否则「一致 N · 差异 M」会被重定向吞掉。
REAL_STDOUT = sys.stdout
(ROOT / "_输出").mkdir(exist_ok=True)
sys.stdout = io.TextIOWrapper(
    open(ROOT / "_输出" / "监听收窄日志.txt", "wb"), encoding="utf-8", write_through=True
)


def report(*values: object) -> None:
    print(*values, file=REAL_STDOUT)


from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatantSpec,
    CombatRequest,
)
from game.core.combat.mechanics import AbilityRuntime  # noqa: E402

#: 与 `tools/语料对照.py` 同一套属性基数：判据比的是两条腿，不是平衡。
ATTRS = {
    "血气上限": 1200, "精神上限": 400, "攻击": 150, "防御": 60, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
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

#: 收窄版是引擎里的真身；跑完两条腿要放回去。
NARROWED = AbilityRuntime._listeners_for


def whole_table(self, context, kind, frame, parties=None):
    """整张排序表：位次就是它在表里的下标，与分桶时算的一致。"""

    return list(enumerate(self._compiled_listeners(context).get(kind, ())))


def spec(pid: str, section: str, cid: str) -> CombatantSpec:
    return CombatantSpec(
        id=pid, name=pid, attributes=dict(ATTRS),
        build=(CombatBuildRef(section, cid, instance_id=f"{pid}:{cid}", born_order=0),),
    )


def digest(raw: dict) -> str:
    """与 `tools/语料对照.py` 的「抹名语义摘要」同一口径。"""

    events = raw.get("events") or ()
    skeleton = [
        (e.get("turn"), e.get("kind"), e.get("source_id"), e.get("target_id"),
         round(float(e.get("amount") or 0), 3))
        for e in events
    ]
    sides = {}
    for side in ("left", "right"):
        masked = copy.deepcopy(raw.get(side) or {})
        for status in masked.get("statuses") or ():
            if isinstance(status, dict) and "name" in status:
                status["name"] = "*"
        sides[side] = masked
    return hashlib.sha256(
        json.dumps([skeleton, sides, raw.get("outcome")], ensure_ascii=False,
                   sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def run_all(listeners_for) -> tuple[dict[str, str], float]:
    AbilityRuntime._listeners_for = listeners_for  # type: ignore[method-assign]
    digests: dict[str, str] = {}
    started = time.perf_counter()
    for section, cid in corpus:
        result = asyncio.run(core.combat.execute(CombatRequest(
            left_team=(spec("L", section, cid),),
            right_team=(spec("R", section, cid),),
            seed=20260911, action_limit=60,
        )))
        raw = dataclasses.asdict(result)
        raw.pop("report", None)
        digests[f"{section}:{cid}"] = digest(raw)
    return digests, time.perf_counter() - started


try:
    narrowed, narrowed_seconds = run_all(NARROWED)
    whole, whole_seconds = run_all(whole_table)
finally:
    AbilityRuntime._listeners_for = NARROWED  # type: ignore[method-assign]
    core.database.close()

differences = [key for key in narrowed if narrowed[key] != whole.get(key)]
for key in differences[:40]:
    report(f"  差异 {key}: 收窄 {narrowed[key]} -> 整表 {whole.get(key)}")
if differences:
    report(f"收窄候选与整张表不一致：{len(narrowed)} 场 · 差异 {len(differences)}")
    sys.exit(1)
report(
    f"收窄候选与整张表逐场一致：{len(narrowed)} 场 · 差异 0"
    f"（收窄 {narrowed_seconds:.1f}s · 整表 {whole_seconds:.1f}s）"
)
