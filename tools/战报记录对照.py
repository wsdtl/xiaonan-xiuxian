"""战报记录对照：日志只记「重要的动作与数据」——同一批仗跑两遍，比骨架、比玩家看得见的那层、比体积。

`展示/战报.json` 的 `标准化.记录事实` 把事实键分成两份：`保留`（进日志）与 `丢弃`
（引擎记账、掷点过程、伤害链中间值——明确想过、决定不记）。引擎在**记录那一刻**筛，
所以不在名单上的键既不进事件、也不进战报与落库记录。

裁剪的危险是「静默丢东西」：少记一个键，战报照旧能出，只是那一行空了。这条判据把两件事
钉在一起跑：

1. **事件骨架逐场一致**（时点 / 类型 / 来源 / 目标 / 数值 / 能力）：裁剪只动事实，不动事件；
2. **简要行与参战者快照逐场一致**：玩家看得见的那一层（页面的「战斗记录」）不许变；
3. **记下来的键全在 `保留` 里**；
4. **语料里出现的键都被决定过**（在 `保留` 或 `丢弃` 里）：冒出一个新键就红，逼作者做决定——
   不然新机制会悄悄往日志里塞账，或者悄悄被丢掉；
5. 顺带把体积账打出来（战报字符 / 明细行数）。

跑哪批：四种卡面各抽若干张（1v1）+ 每个战场环境一场 + 每座阵法一场（黄品）+ 一对阵对阵。
**阵法与地势那些键在 1v1 语料里根本不出现**，只抽卡面盖不到。

    .venv/Scripts/python.exe -X utf8 tools/战报记录对照.py
    .venv/Scripts/python.exe -X utf8 tools/战报记录对照.py --卡数 20     # 快速自检

**退出码：0 = 一致，1 = 有差异。**
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--数据", dest="数据", default="", help="要跑的数据目录；默认 data，或环境变量 CORPUS_DATA")
parser.add_argument("--卡数", dest="卡数", type=int, default=24, help="四个卡面各抽多少张（默认 24）")
args = parser.parse_args()

DATA_DIR = Path(args.数据 or os.environ.get("CORPUS_DATA") or ROOT / "data").resolve()

# 过程输出写日志文件，判定结论回到真终端（与其它通道一致）。
REAL_STDOUT = sys.stdout
(ROOT / "_输出").mkdir(exist_ok=True)
sys.stdout = io.TextIOWrapper(
    open(ROOT / "_输出" / "战报记录日志.txt", "wb"), encoding="utf-8", write_through=True
)


def report(*values: object) -> None:
    print(*values, file=REAL_STDOUT)


from game.app import build_game_services  # noqa: E402
from game.core.combat.contracts import (  # noqa: E402
    CombatBuildRef,
    CombatFieldSpec,
    CombatFormationSpec,
    CombatReportSpec,
    CombatRequest,
    CombatantSpec,
)

FIXED_GENERATED_AT = "2026-01-01T00:00:00+08:00"
CARD = "400541"
SURFACES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("器律", "物品/炼器/内容/器律-*.json"),
)
#: 与 `tools/语料对照.py` 同一套基数：这条判据比的是两条腿，不是平衡。
ATTRS = {
    "血气上限": 1200, "精神上限": 400, "攻击": 150, "防御": 60, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 100, "伤害减免": 0,
}
#: 战场环境与阵法要打得久一点：阶段推进与轮转才发生得了（抄 `tools/阵法对照.py` 的口径）。
FIELD_ATTRS = {
    "血气上限": 2600, "精神上限": 900, "攻击": 300, "防御": 50, "速度": 110,
    "命中率": 100, "闪避率": 5, "暴击率": 20, "抗暴率": 5, "暴击伤害": 150,
    "格挡率": 10, "破格率": 5, "格挡减伤": 30, "伤害加成": 100, "伤害减免": 0,
}
FORMATION_ATTRS = {
    "血气上限": 9000, "精神上限": 2000, "攻击": 50, "防御": 200, "速度": 100,
    "命中率": 100, "闪避率": 0, "暴击率": 0, "抗暴率": 0, "暴击伤害": 150,
    "格挡率": 0, "破格率": 0, "格挡减伤": 0, "伤害加成": 100, "伤害减免": 50,
}
VERSUS_GRADE = "黄"


def side(pid: str, attrs: dict[str, float], section: str = "功法", cid: str = CARD) -> CombatantSpec:
    return CombatantSpec(
        id=pid, name=pid, attributes=dict(attrs),
        build=(CombatBuildRef(section, cid, instance_id=f"{pid}:{cid}", born_order=0),),
    )


def 报告(请求: CombatRequest) -> CombatRequest:
    return dataclasses.replace(
        请求, report=CombatReportSpec(scene="对照", generated_at=FIXED_GENERATED_AT, include_presentation=True)
    )


def 语料样本() -> list[tuple[str, CombatRequest]]:
    """每个面**均匀抽**若干张：顺着文件取前几张会全落在同一批家族上。"""

    脚本 = []
    for 节, 模式 in SURFACES:
        编号表: list[str] = []
        for 路径 in sorted(DATA_DIR.glob(模式)):
            for 卡 in json.loads(路径.read_text(encoding="utf-8")):
                编号表.append(str(卡["编号"]))
        if not 编号表:
            continue
        步 = max(1, len(编号表) // args.卡数)
        取 = 编号表[::步][: args.卡数]
        for 编号 in 取:
            脚本.append((f"{节}:{编号}", 报告(CombatRequest(
                left_team=(side("L", ATTRS, 节, 编号),),
                right_team=(side("R", ATTRS, 节, 编号),),
                seed=20260911, action_limit=60,
            ))))
    return 脚本


def 全部场景(核心) -> list[tuple[str, CombatRequest]]:
    脚本 = 语料样本()
    for 环境 in sorted(核心.combat._require_engine().catalog.environments):
        脚本.append((f"环境:{环境}", 报告(CombatRequest(
            left_team=(side("L", FIELD_ATTRS),), right_team=(side("R", FIELD_ATTRS),),
            seed=20260915, action_limit=120,
            field=CombatFieldSpec(
                environment_id=环境, origin="地表", scene="对照", xy=(1, 1), altitude=100, terrain="平原"
            ),
        ))))
    阵法 = sorted(item.formation_id for item in 核心.formation.formations())
    for 编号 in 阵法:
        脚本.append((f"阵法:{编号}", 报告(CombatRequest(
            left_team=(side("L", FORMATION_ATTRS),), right_team=(side("R", FORMATION_ATTRS),),
            seed=20260915, action_limit=220,
            left_formation=CombatFormationSpec(formation_id=编号, grade=VERSUS_GRADE, position=0),
            right_formation=None,
        ))))
    脚本.append(("阵法对阵", 报告(CombatRequest(
        left_team=(side("L", FORMATION_ATTRS),), right_team=(side("R", FORMATION_ATTRS),),
        seed=20260915, action_limit=300,
        left_formation=CombatFormationSpec(formation_id="530001", grade=VERSUS_GRADE, position=0),
        right_formation=CombatFormationSpec(formation_id="530002", grade=VERSUS_GRADE, position=1),
    ))))
    return 脚本


def 骨架(结果) -> list[tuple]:
    return [
        (e.turn, e.kind, e.source_id, e.target_id, round(e.amount, 3), e.ability)
        for e in 结果.events
    ]


def 显示(结果) -> list[tuple]:
    """玩家看得见的那层：简要行 + 参战者快照（当前资源与状态）。"""

    份 = 结果.presentation
    层 = list(份) if isinstance(份, (list, tuple)) else [份]
    行: list[tuple] = []
    for 一块 in 层:
        if not isinstance(一块, dict):
            continue
        for 段 in (一块.get("segments") or {}).values():
            for 条 in (段.get("segment") or {}).get("timeline") or []:
                for 事 in 条.get("summary_events") or ():
                    行.append(("行", 事.get("kind"), 事.get("label"), 事.get("text")))
        for 名, 表 in (一块.get("participants") or {}).items():
            if isinstance(表, dict):
                行.append((
                    "参战者", str(名),
                    json.dumps(表.get("resources"), ensure_ascii=False, sort_keys=True),
                    json.dumps(表.get("statuses"), ensure_ascii=False, sort_keys=True),
                ))
    return 行


def 跑一遍(核心, 引擎, 请求: CombatRequest, 名单) -> tuple[list, list, int, int, int, set]:
    引擎.recorded_facts = 名单
    结果 = asyncio.run(核心.combat.execute(请求))
    报 = json.dumps(结果.report, ensure_ascii=False, sort_keys=True)
    展 = json.dumps(结果.presentation, ensure_ascii=False, sort_keys=True)
    行数 = sum(len(事件.get("details") or ()) for 事件 in (结果.report or {}).get("events") or ())
    键 = {键 for 事件 in 结果.events for 键 in 事件.values}
    return 骨架(结果), 显示(结果), len(报), len(展), 行数, 键


配置 = json.loads((DATA_DIR / "战斗" / "展示" / "战报.json").read_text(encoding="utf-8"))
声明 = 配置["标准化"]["记录事实"]
保留 = {str(键) for 键 in 声明["保留"]}
丢弃 = {str(键) for 键 in 声明["丢弃"]}

问题: list[str] = []
重叠 = 保留 & 丢弃
if 重叠:
    问题.append("同一批键同时写在保留与丢弃里：" + "、".join(sorted(重叠)))
内部 = {str(键) for 键 in 配置["标准化"]["内部明细"]}
不在丢弃里 = 内部 - 丢弃
if 不在丢弃里:
    问题.append("内部明细没进丢弃名单（屏上不显示的账别记）：" + "、".join(sorted(不在丢弃里)))

服务 = build_game_services(data_dir=DATA_DIR)
try:
    核心 = 服务.core
    引擎 = 核心.combat._require_engine()
    名单 = 引擎.recorded_facts
    if 名单 is None:
        问题.append("战斗核心没有接线记录名单：日志会全记（`service` 初始化时要把它交给引擎）")
        名单 = frozenset(保留)
    脚本 = 全部场景(核心)
    骨架差 = 显示差 = 越界 = 未决定 = 0
    全记报 = 筛后报 = 全记行 = 筛后行 = 0
    样例: dict[str, str] = {}
    for 名, 请求 in 脚本:
        甲 = 跑一遍(核心, 引擎, 请求, None)
        乙 = 跑一遍(核心, 引擎, 请求, 名单)
        if 甲[0] != 乙[0]:
            骨架差 += 1
            问题.append(f"事件骨架不一致：{名}")
        if 甲[1] != 乙[1]:
            显示差 += 1
            问题.append(f"简要行 / 参战者快照不一致：{名}")
        全记报 += 甲[2]; 筛后报 += 乙[2]; 全记行 += 甲[4]; 筛后行 += 乙[4]
        for 键 in 乙[5]:
            if 键 not in 保留:
                越界 += 1
                样例.setdefault(键, 名)
        for 键 in 甲[5]:
            if 键 not in 保留 and 键 not in 丢弃:
                未决定 += 1
                样例.setdefault(键, 名)
    for 键, 名 in sorted(样例.items()):
        if 键 in 丢弃:
            问题.append(f"把「决定不记」的键记了进来：{键}（{名}）")
        else:
            问题.append(f"语料里出现了没决定过的键（保留或丢弃里都没有）：{键}（{名}）")
finally:
    服务.core.database.close()

下降 = (1 - 筛后报 / 全记报) * 100 if 全记报 else 0.0
行下降 = (1 - 筛后行 / 全记行) * 100 if 全记行 else 0.0
if 问题:
    for 文本 in 问题[:40]:
        report("  " + 文本)
    report(f"战报记录有问题：{len(脚本)} 场 · {len(问题)} 处")
    sys.exit(1)
report(
    f"战报记录一致：{len(脚本)} 场 · 骨架差异 0 · 简要行差异 0 · 越界键 0 · 未决定键 0"
    f"（战报 {全记报 / 1e6:.1f}M→{筛后报 / 1e6:.1f}M 字符 -{下降:.0f}% · "
    f"明细行 {全记行}→{筛后行} -{行下降:.0f}%）"
)
