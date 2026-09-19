"""战斗核心的每一个数据入口都必须被真实驱动。

只测「我改了什么」会漏掉整条链路：战前状态（战丹、长期伤势）走的是
`prepared_statuses`，战场环境走 `field`，阵法走 `formation`，恢复丹走
`medicine_definitions`——它们的装配入口各不相同，任何一条没被驱动过，
就可能藏着「一用就崩」的缺陷。

本文件按数据的**入口**组织，而不是按改动面组织。批量扫描只求装配与解析不崩，
深层路径另用事件种类断言，防止测试退化成空跑。
"""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from game.core.combat.contracts import (
    CombatBuildRef,
    CombatFieldSpec,
    CombatFormationSpec,
    CombatGroupSpec,
    CombatMedicineSpec,
    CombatantReportSpec,
    CombatantSpec,
    CombatReportSpec,
    CombatRequest,
)

DATA = Path(__file__).resolve().parents[1] / "data"
ATTRS = {
    "血气上限": 1200,
    "精神上限": 400,
    "攻击": 150,
    "防御": 60,
    "速度": 110,
    "命中率": 100,
    "闪避率": 5,
    "暴击率": 20,
    "抗暴率": 5,
    "暴击伤害": 150,
    "格挡率": 10,
    "破格率": 5,
    "格挡减伤": 30,
    # 加成口径的基准是 100（不增不减）：这里写 0 等于「伤害加成 0%」，会把伤害乘成 0。
    "伤害加成": 100,
    "伤害减免": 0,
}
GRADES = ("黄", "玄", "地", "天")
CARD = "400541"


def _load(pattern: str) -> list[dict]:
    entries: list[dict] = []
    for path in sorted(DATA.glob(pattern)):
        document = json.loads(path.read_text(encoding="utf-8"))
        entries.extend(document if isinstance(document, list) else [document])
    return entries


@pytest.fixture(scope="module")
def services(tmp_path_factory):
    import game.app as app
    from main import create_app

    create_app()
    isolated = replace(
        app.game_config.database, path=tmp_path_factory.mktemp("db") / "game.db"
    )
    original = app.game_config
    app.game_config = replace(app.game_config, database=isolated)
    try:
        built = app.build_game_services(data_dir=DATA)
    finally:
        app.game_config = original
    try:
        yield built.core
    finally:
        built.core.database.close()


def _spec(pid: str, cards: tuple[str, ...] = (CARD,), **kwargs) -> CombatantSpec:
    return CombatantSpec(
        id=pid,
        name=pid,
        attributes=dict(ATTRS),
        build=tuple(
            CombatBuildRef("功法", cid, instance_id=f"{pid}:{cid}", born_order=index)
            for index, cid in enumerate(cards)
        ),
        **kwargs,
    )


def _fight(services, *, limit: int = 8, **kwargs) -> object:
    params: dict = {
        "left_team": (_spec("L"),),
        "right_team": (_spec("R"),),
        "seed": 20260911,
        "action_limit": limit,
    }
    params.update(kwargs)
    return asyncio.run(services.combat.execute(CombatRequest(**params)))


def _failures(services, cases: list[tuple[str, dict]], limit: int = 8) -> list[str]:
    broken: list[str] = []
    for label, kwargs in cases:
        try:
            _fight(services, limit=limit, **kwargs)
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{label}: {type(exc).__name__}: {exc}")
    return broken


def test_every_environment_fights(services) -> None:
    """55 个战场环境 × 地表/秘境两种来源。"""

    environments = _load("战斗/内容/战场环境/*.json")
    assert len(environments) >= 50

    cases: list[tuple[str, dict]] = []
    for entry in environments:
        environment_id = str(entry["编号"])
        name = str(entry["名称"])
        cases.append(
            (
                f"地表 {environment_id} {name}",
                {
                    "left_team": (_spec("L", (CARD, "400004")),),
                    "right_team": (_spec("R", ("400005",)),),
                    "field": CombatFieldSpec(
                        environment_id=environment_id,
                        scene=name,
                        origin="地表",
                        xy=(100, 100),
                        altitude=100,
                        terrain=name,
                    ),
                },
            )
        )
        cases.append(
            (
                f"秘境 {environment_id} {name}",
                {
                    "field": CombatFieldSpec(
                        environment_id=environment_id, scene=name, origin="秘境"
                    )
                },
            )
        )
    assert not _failures(services, cases)


def test_every_formation_grade_fights(services) -> None:
    """46 座阵法 × 黄玄地天，以及需要真实材料投入的圣品。"""

    formations = [
        entry
        for entry in _load("物品/阵法/内容/*.json")
        if isinstance(entry, dict) and str(entry.get("编号", "")).startswith("53")
    ]
    assert len(formations) >= 40

    cases: list[tuple[str, dict]] = []
    for entry in formations:
        formation_id = str(entry["编号"])
        name = str(entry.get("名称"))
        for grade in GRADES:
            cases.append(
                (
                    f"{formation_id} {name} {grade}品",
                    {
                        "left_formation": CombatFormationSpec(
                            formation_id=formation_id, grade=grade, position=0
                        ),
                        "right_formation": CombatFormationSpec(
                            formation_id=formation_id, grade=grade, position=0
                        ),
                    },
                )
            )
        holy = next(
            (
                block
                for block in entry.get("品级") or ()
                if str(block.get("品级")) == "圣"
            ),
            None,
        )
        if holy is None:
            continue
        materials = {
            str(key): float(value)
            for key, value in (holy.get("最低消耗") or {}).items()
        }
        assert materials, f"{formation_id} 的圣品缺少最低消耗"
        cases.append(
            (
                f"{formation_id} {name} 圣品",
                {
                    "left_formation": CombatFormationSpec(
                        formation_id=formation_id, grade="圣", materials=materials
                    )
                },
            )
        )
    assert not _failures(services, cases)


def test_every_recovery_pill_can_be_used(services) -> None:
    """6 种恢复丹都要能装配，并在对应资源偏低时被真正服用。"""

    pills = _load("物品/炼丹/内容/丹药/恢复丹/*.json")
    assert len(pills) >= 6
    resource_of = {"恢复血气": "血气", "恢复精神": "精神"}

    broken: list[str] = []
    for entry in pills:
        effect = entry.get("使用效果") or {}
        resource = resource_of.get(str(effect.get("类型")))
        assert resource is not None, f"{entry['编号']} 恢复类型未登记：{effect.get('类型')}"
        stack = f"L:{entry['编号']}"
        # 血气与精神都压到阈值以下，两种恢复丹才会各自触发。
        try:
            result = _fight(
                services,
                limit=60,
                left_team=(
                    _spec(
                        "L",
                        health=200,
                        spirit=50,
                        inventory={stack: 9},
                        inventory_owner_id="L",
                        auto_medicine=True,
                        medicine_threshold=0.99,
                    ),
                ),
                medicine_definitions=(
                    CombatMedicineSpec(
                        stack,
                        str(entry["编号"]),
                        "01",
                        resource,
                        float(effect.get("恢复百分比") or 0),
                        1,
                    ),
                ),
                medicine_selection_strategy=services.medicine.selection_strategy,
            )
        except Exception as exc:  # noqa: BLE001
            broken.append(f"{entry['编号']} {entry['名称']}: {type(exc).__name__}: {exc}")
            continue
        kinds = {event.kind for event in result.events}
        if "使用丹药后" not in kinds:
            broken.append(f"{entry['编号']} {entry['名称']}（{resource}）没有被服用")
    assert not broken, broken


def test_entry_surfaces_reach_their_deep_paths(services) -> None:
    """批量扫描只保证不崩；这里确认环境阶段、阵法轮转和用丹真的被走到。"""

    environment = _load("战斗/内容/战场环境/*.json")[0]
    result = _fight(
        services,
        limit=200,
        left_team=(_spec("L", (CARD, "400004")),),
        right_team=(_spec("R", ("400005",)),),
        field=CombatFieldSpec(
            environment_id=str(environment["编号"]),
            scene=str(environment["名称"]),
            origin="地表",
            xy=(100, 100),
            altitude=100,
            terrain=str(environment["名称"]),
        ),
    )
    environment_kinds = {event.kind for event in result.events}
    assert "地势承伤后" in environment_kinds, "战场环境没有推进承伤阶段"

    formation = next(
        entry
        for entry in _load("物品/阵法/内容/*.json")
        if isinstance(entry, dict) and str(entry.get("编号", "")).startswith("53")
    )
    # 首轮阵法轮转要等到 `ceil(12 × 周期倍率 / 传导)` 个行动之后，而一场仗有多长
    # 取决于全局伤害量级（`输出倍率`）。这里要验的是「轮转这条路走得到」，
    # 不是「战斗该有多长」，所以自己把血池撑到足以跨过一次轮转，
    # 免得以后每次调平衡都来踩这个断言。
    sturdy = replace(_spec("L"), attributes={**ATTRS, "血气上限": 200_000})
    result = _fight(
        services,
        limit=120,
        left_team=(sturdy,),
        right_team=(replace(sturdy, id="R", name="R"),),
        left_formation=CombatFormationSpec(formation_id=str(formation["编号"]), grade="黄"),
        right_formation=CombatFormationSpec(formation_id=str(formation["编号"]), grade="黄"),
    )
    formation_kinds = {event.kind for event in result.events}
    assert {"阵法展开", "阵法轮转后", "阵法冲击后"} <= formation_kinds, "阵法没有完整轮转"


def test_groups_report_and_snapshots(services) -> None:
    """编组、战报、原始状态快照、五行根性、装备与冷却都要能提交。"""

    result = _fight(
        services,
        limit=20,
        left_team=(_spec("L1"), _spec("L2")),
        right_team=(_spec("R1"), _spec("R2")),
        left_groups=(CombatGroupSpec("G-L", ("L1", "L2"), ("L1",)),),
        right_groups=(CombatGroupSpec("G-R", ("R1", "R2"), ("R1",)),),
    )
    assert result.left_results and result.right_results

    result = _fight(
        services,
        limit=20,
        report=CombatReportSpec(
            participants=(
                CombatantReportSpec("L", title="左", color="#fff"),
                CombatantReportSpec("R", title="右", color="#000"),
            ),
            scene="测试战场",
            include_presentation=True,
        ),
    )
    assert result.report is not None

    _fight(
        services,
        limit=20,
        left_team=(
            _spec(
                "L",
                gender="男",
                level=30,
                shield=300,
                health=900,
                spirit=300,
                skill_cursor=1,
                cooldowns={f"L:{CARD}:0": 2},
                five_elements={"木": 50, "火": 50, "土": 0, "金": 0, "水": 0},
                statuses=(
                    {
                        "名称": "测试状态",
                        "类别": "负面",
                        "剩余行动": 2,
                        "属性": {"防御": -5},
                        "层数": 1,
                        "层数上限": 1,
                        "标签": ["测试"],
                    },
                ),
            ),
        ),
        right_team=(_spec("R", gender="女", shield=100),),
    )
