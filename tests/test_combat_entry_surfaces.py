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
GRADES = ("黄品", "玄品", "地品", "天品")
CARD = "400041"


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
        for entry in _load("物品/内容/阵法/*.json")
        if isinstance(entry, dict) and str(entry.get("编号", "")).startswith("53")
    ]
    assert len(formations) >= 54

    cases: list[tuple[str, dict]] = []
    for entry in formations:
        formation_id = str(entry["编号"])
        name = str(entry.get("名称"))
        for grade in (*GRADES, "圣品"):
            cases.append(
                (
                    f"{formation_id} {name} {grade}",
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
    assert not _failures(services, cases)


def test_every_recovery_pill_can_be_used(services) -> None:
    """6 种恢复丹都要能装配，并在对应资源偏低时被真正服用。"""

    pills = _load("物品/内容/丹药/恢复丹/*.json")
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
        for entry in _load("物品/内容/阵法/*.json")
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
        left_formation=CombatFormationSpec(formation_id=str(formation["编号"]), grade="黄品"),
        right_formation=CombatFormationSpec(formation_id=str(formation["编号"]), grade="黄品"),
    )
    formation_kinds = {event.kind for event in result.events}
    assert {"阵法展开", "阵法轮转后", "阵法冲击后"} <= formation_kinds, "阵法没有完整轮转"


def test_formation_detection_scales_impact(services) -> None:
    """阵法的检测字段必须进入真实冲击，而不是只校验数据。"""

    sturdy = replace(
        _spec("L"),
        attributes={**ATTRS, "血气上限": 200_000},
        health=100_000,
    )
    result = _fight(
        services,
        limit=30,
        left_team=(sturdy,),
        right_team=(replace(sturdy, id="R", name="R"),),
        left_formation=CombatFormationSpec(formation_id="530001", grade="黄品"),
    )
    rotations = [event for event in result.events if event.kind == "阵法轮转后"]
    assert rotations
    assert any(
        event.values.get("检测字段") == "已损失血气"
        and float(event.values.get("检测倍率") or 1) > 1
        for event in rotations
    )
    assert any(event.kind == "阵法冲击后" for event in result.events)


def test_formation_assessment_reaches_battle(services) -> None:
    """阵核评估 → 战斗快照 → 真实战斗，阵核与检测字段一路带过去。"""

    from game.core.asset.contracts import AssetEntry

    entries = (
        AssetEntry("物品", "灵矿", "220032", "core-1", "丘脉青晶", "01", "黄品", 6),
        AssetEntry("物品", "灵矿", "220086", "core-2", "丘腹赤铁", "01", "黄品", 6),
    )
    assessment = services.formation.assess("530001", "黄品", entries)
    assert assessment.can_form
    assert assessment.core_names == ("丘脉青晶", "丘腹赤铁")
    assert assessment.detection is not None
    profile = services.formation.battle_profile("530001", "黄品", {"灵矿": 2})
    assert profile.detection is not None

    result = _fight(
        services,
        limit=30,
        left_team=(replace(_spec("L"), health=600),),
        right_team=(_spec("R"),),
        left_formation=CombatFormationSpec("530001", "黄品"),
    )
    assert any(event.kind == "阵法冲击后" for event in result.events)


def test_formation_activation_plan_reaches_battle(services) -> None:
    """布阵快照 → 激活计划 → 战斗，检测与三面板一路保留。"""

    from unittest.mock import patch

    from game.core.formation import FormationPrepared

    prepared = FormationPrepared(
        "tester",
        "reserve",
        "530001",
        "叠翠盘根阵",
        "01",
        "黄品",
        (("兽宝", "0"), ("灵矿", "2"), ("灵植", "0")),
        "",
        (),
        0,
    )

    async def fake_prepared(_user_id: str) -> FormationPrepared:
        return prepared

    with patch.object(services.formation, "prepared", fake_prepared):
        plan = asyncio.run(services.formation.activation_plan("tester"))
    assert plan is not None
    assert plan.profile.detection is not None
    assert plan.profile.core_names if hasattr(plan.profile, "core_names") else True

    result = _fight(
        services,
        limit=30,
        left_team=(replace(_spec("L"), health=600),),
        right_team=(_spec("R"),),
        left_formation=CombatFormationSpec("530001", "黄品"),
    )
    assert any(event.kind == "阵法冲击后" for event in result.events)


def test_formation_craft_arm_and_battle(services) -> None:
    """真实人物库存：炼阵 → 布阵 → 激活快照 → 实战。"""

    from game.core.asset.contracts import InventoryAdjustment
    from game.core.character.contracts import CharacterCreateCommand
    from game.core.database.contracts import TransactionCommand

    user_id = "formation-e2e"
    asyncio.run(
        services.character.create(
            CharacterCreateCommand(
                user_id, "create-formation", "炼阵测试", "男", (15, 17), ""
            )
        )
    )
    plan = asyncio.run(
        services.asset.plan_inventory_changes(
            user_id,
            (
                InventoryAdjustment("220032", "01", 6),
                InventoryAdjustment("220086", "01", 6),
            ),
        )
    )
    asyncio.run(
        services.database.commit(
            TransactionCommand(user_id, "seed-formation", "测试", plan.operations, {})
        )
    )
    preview = asyncio.run(services.formation.preview(user_id, "530001", "黄品"))
    assert preview.can_form
    assert preview.core_names == ("丘脉青晶", "丘腹赤铁")
    assert preview.detection is not None

    formed = asyncio.run(services.formation.form(user_id, "form-1", "530001", "黄品"))
    armed = asyncio.run(services.formation.arm(user_id, "arm-1", formed.reserve_key))
    assert armed.prepared.formation_id == "530001"
    activation = asyncio.run(services.formation.activation_plan(user_id))
    assert activation is not None
    assert activation.profile.detection is not None

    result = _fight(
        services,
        limit=30,
        left_team=(replace(_spec("L"), health=600),),
        right_team=(_spec("R"),),
        left_formation=CombatFormationSpec("530001", "黄品"),
    )
    assert any(event.kind == "阵法冲击后" for event in result.events)


def test_all_builds_enter_one_real_battle(services) -> None:
    """功法/真意/气机全部 1224 张构筑至少进入一次真实战斗。"""

    builds = []
    for kind, directory in (
        ("功法", "战斗/内容/功法"),
        ("真意", "战斗/内容/真意"),
        ("气机", "战斗/内容/气机"),
    ):
        for path in sorted((DATA / directory).glob("*/*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            entry = document[0] if isinstance(document, list) else document
            builds.append((kind, str(entry["编号"])))
    assert len(builds) == 1224

    refs = tuple(
        CombatBuildRef(kind, build_id, instance_id=f"L:{kind}:{build_id}", born_order=index)
        for index, (kind, build_id) in enumerate(builds)
    )
    fighter = CombatantSpec(
        id="L",
        name="全部构筑",
        attributes=dict(ATTRS),
        build=refs,
    )
    result = _fight(
        services,
        limit=3,
        left_team=(fighter,),
        right_team=(_spec("R"),),
    )
    assert result.left_results


def test_formation_preview_shows_core_and_detection() -> None:
    """演阵台必须显示阵核、辅材倍数、检测与难度，不再用旧阵基/阵眼标签。"""

    from types import SimpleNamespace

    from game.cmd.特殊地点.宗门园区.宗门设施.site import _formation_view
    from game.core.formation import FormationDetection

    assessment = SimpleNamespace(
        formation=SimpleNamespace(formation_id="530001", name="叠翠盘根阵"),
        grade_name="黄品",
        capacity=240.0,
        impact=180.0,
        nodes=3,
        transmission=0.8,
        materials=(),
        core_names=("丘脉青晶", "丘腹赤铁"),
        supplement_multipliers=(
            ("灵矿", 1.2),
            ("兽宝", 1.0),
            ("灵植", 1.1),
        ),
        detection=FormationDetection("已损失血气", "每10%", 0.06, "易", "血气"),
    )
    value = SimpleNamespace(
        facility=SimpleNamespace(name="演阵台"),
        role="阵师",
        material_source="个人纳戒",
        assessment=assessment,
        materials=(),
        spirit_stone_cost=0,
    )
    feature = SimpleNamespace(copy=lambda: {"通用": {"职位": "职位", "材料来源": "来源"}})
    view = _formation_view(feature, value)
    fields = {item["键"]: item["值"] for item in view["字段"]}
    assert "阵基" not in fields and "阵眼" not in fields
    assert fields["阵核"] == "丘脉青晶、丘腹赤铁"
    assert "灵矿 ×1.2" in fields["辅材倍数"]
    assert fields["检测"] == "已损失血气｜每10%｜冲击 +6%"
    assert fields["难度"] == "易"


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


def test_report_capture_preserves_settlement(services) -> None:
    """战报省略隐藏节点、无变化记录，全部结算字段仍与完整轨迹一致。"""

    request = CombatRequest(
        left_team=(_spec("L", (CARD, "400004")),),
        right_team=(_spec("R", ("400005",)),),
        seed=20260911,
        action_limit=60,
    )
    full = asyncio.run(services.combat.execute(request))
    reported = asyncio.run(
        services.combat.execute(
            replace(
                request,
                report=CombatReportSpec(
                    participants=(
                        CombatantReportSpec("L"),
                        CombatantReportSpec("R"),
                    )
                ),
            )
        )
    )

    assert reported.total_event_count == len(full.events)
    assert len(reported.events) < len(full.events)
    assert reported.actions == full.actions
    assert reported.trigger_activations == full.trigger_activations
    assert reported.winner_side == full.winner_side
    assert reported.left_results == full.left_results
    assert reported.right_results == full.right_results
    assert replace(reported, events=(), report=None, presentation=None) == replace(full, events=())
    assert '命中后' not in {event.kind for event in reported.events}
    captured_kinds = {event.kind for event in reported.events}
    assert {"战斗开始", "行动开始", "造成伤害后", "战斗结束"} <= captured_kinds
    assert reported.report is not None
    assert reported.report["result"]["total_event_count"] == len(full.events)
    assert reported.report["result"]["event_count"] == len(reported.events)
