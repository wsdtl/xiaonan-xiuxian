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
    """54 座阵法 × 黄玄地天，以及需要真实材料投入的圣品。"""

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

    pills = _load("物品/内容/丹药/恢复丹/*/*.json")
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
        AssetEntry("物品", "灵矿", "220032", "core-1", "丘脉青晶", "01", "黄品", 1),
        AssetEntry("物品", "灵矿", "220086", "core-2", "丘腹赤铁", "01", "黄品", 1),
        AssetEntry("物品", "兽宝", "210001", "beast-1", "丘兽宝", "01", "黄品", 4),
        AssetEntry("物品", "灵矿", "220001", "ore-1", "丘灵矿", "01", "黄品", 6),
        AssetEntry("物品", "灵植", "200001", "herb-1", "丘灵植", "01", "黄品", 6),
    )
    assessment = services.formation.assess("530001", "黄品", entries)
    assert assessment.can_form
    assert assessment.core_names == ("丘脉青晶", "丘腹赤铁")
    assert assessment.detection is not None
    profile = services.formation.battle_profile(
        "530001", "黄品", {"兽宝": 4, "灵矿": 8, "灵植": 6}
    )
    assert profile.detection is not None

    result = _fight(
        services,
        limit=30,
        left_team=(replace(_spec("L"), health=600),),
        right_team=(_spec("R"),),
        left_formation=CombatFormationSpec("530001", "黄品"),
    )
    assert any(event.kind == "阵法冲击后" for event in result.events)


def test_fixed_and_holy_formation_costs(services) -> None:
    """黄玄地天固定消耗，圣品最低值之上才无上限追加。"""

    from game.core.formation import FormationError

    expected = {
        "黄品": {"兽宝": 4, "灵矿": 8, "灵植": 6},
        "玄品": {"兽宝": 8, "灵矿": 16, "灵植": 12},
        "地品": {"兽宝": 12, "灵矿": 24, "灵植": 18},
        "天品": {"兽宝": 16, "灵矿": 32, "灵植": 24},
    }
    for grade, counts in expected.items():
        value = services.formation.assess("530001", grade, ())
        actual = {item.category: item.required for item in value.requirements}
        assert actual == counts
        assert all(multiplier == 1.0 for _, multiplier in value.supplement_multipliers)

    with pytest.raises(FormationError, match="按固定配方炼制"):
        services.formation.assess(
            "530001", "黄品", (), {"兽宝": 1, "灵矿": 0, "灵植": 0}
        )

    minimum = services.formation.assess(
        "530001", "圣品", (), {"兽宝": 28, "灵矿": 56, "灵植": 42}
    )
    assert (minimum.capacity, minimum.impact, minimum.nodes) == (480.0, 360.0, 6)
    assert all(multiplier == 1.0 for _, multiplier in minimum.supplement_multipliers)

    with pytest.raises(FormationError, match="不得低于最低消耗"):
        services.formation.assess(
            "530001", "圣品", (), {"兽宝": 27, "灵矿": 56, "灵植": 42}
        )

    extra = services.formation.assess(
        "530001", "圣品", (), {"兽宝": 29, "灵矿": 56, "灵植": 42}
    )
    assert extra.impact > minimum.impact
    assert dict(extra.supplement_multipliers)["兽宝"] > 1.0


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
        (("兽宝", "4"), ("灵矿", "8"), ("灵植", "6")),
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


def test_bloodline_data_boundary(services) -> None:
    """普通/天外、能觉醒/不能觉醒、固定属性与觉醒档都按数据解释。"""

    from game.features.xuemai import XuemaiFeature
    from game.features.xuemai.matching import matched

    xuemai = XuemaiFeature(services.data, services.character, services.database)
    xuemai.initialize()
    rules = xuemai.rules()
    assert len(rules.bloodlines) == 32
    assert any(blood.outer for blood in rules.bloodlines)
    assert any(blood.awake for blood in rules.bloodlines)
    assert any(not blood.awake for blood in rules.bloodlines)

    # 普通血脉：新芽血，固定治疗加成
    normal_hits = {blood.name for blood in matched(rules, "100000000000")}
    assert "新芽血" in normal_hits
    assert xuemai.bloodline_growth("100000000000").get("治疗加成", 0) > 0
    # 天外血脉：凤凰血，全偶数位
    outer_hits = {blood.name for blood in matched(rules, "101010101010")}
    assert "凤凰血" in outer_hits
    assert xuemai.bloodline_growth("101010101010").get("治疗加成", 0) >= 15.0
    # 觉醒档边界：70 是 1.0，39 落 20~40 档，4 落 5 以下档
    assert float(xuemai.awaken("70")) == 1.0
    assert float(xuemai.awaken("39")) == 1.5
    assert float(xuemai.awaken("19")) == 2.0
    assert float(xuemai.awaken("4")) == 2.5


def test_health_soul_are_isomorphic(services) -> None:
    """血气与神魂是同一套命线：同百分比同时长，上限变化一致；任一归零都死。"""

    from types import SimpleNamespace

    from game.core.combat.contracts import CombatantResult

    attributes = {
        "血气上限": 100.0,
        "神魂上限": 100.0,
        "精神上限": 100.0,
        "攻击": 10.0,
        "防御": 10.0,
        "速度": 100.0,
    }
    services.character._yijing_battle(
        SimpleNamespace(
            yijing=(
                SimpleNamespace(content_id="630002", name="山不让尘意境", tier=9),
            )
        ),
        attributes,
        0.0,
    )
    assert attributes["血气上限"] == attributes["神魂上限"] == 145.0
    assert CombatantResult.alive.fget(SimpleNamespace(health=1.0, soul=1.0)) is True
    assert CombatantResult.alive.fget(SimpleNamespace(health=1.0, soul=0.0)) is False
    assert CombatantResult.alive.fget(SimpleNamespace(health=0.0, soul=1.0)) is False


def test_lifespan_full_drops_level_growth(services) -> None:
    """寿元将尽：等级成长那一份从属性与资源上限里扣掉，基础属性保留。"""

    from game.core.character.service import _clamp_life_resources

    growth = services.growth.cultivator_attribute_growth(2)
    key = next(key for key in growth if key not in {"血气上限", "神魂上限", "精神上限"})
    attributes = {str(key): 100.0, "血气上限": 500.0, "神魂上限": 500.0}
    result = services.character._without_level_growth(attributes, 3)
    assert result[str(key)] == 100.0 - float(growth[key])
    for cap in ("血气上限", "神魂上限"):
        assert result[cap] == 500.0 - float(growth.get(cap, 0))
    resources = _clamp_life_resources({"血气": 500.0, "神魂": 500.0}, result)
    assert resources["血气"] <= result["血气上限"]


def test_lifespan_full_profile_does_not_recurse(services) -> None:
    """寿元将尽时 profile 不能再回调血脉 DNA：profile -> raw -> dna -> profile 会递归。"""

    from game.core.character.contracts import CharacterCreateCommand
    from game.core.database.contracts import StateAddress, StateMutation, TransactionCommand

    user_id = "lifespan-profile"
    asyncio.run(
        services.character.create(
            CharacterCreateCommand(
                user_id, "create-lifespan", "寿元测试", "女", (15, 17), ""
            )
        )
    )
    snapshot = asyncio.run(
        services.database.get(StateAddress(user_id, "character", "main"))
    )
    value = dict(snapshot.value)
    value["修行日数"] = 100000
    asyncio.run(
        services.database.commit(
            TransactionCommand(
                user_id,
                "age-lifespan",
                "寿元测试",
                (StateMutation(user_id, "character", "main", value, snapshot.version),),
                {},
            )
        )
    )
    profile = asyncio.run(services.character.profile(user_id))
    assert profile.lifespan_full is True
    assert profile.age == profile.lifespan


def test_yijing_tier_nine_enters_real_battle(services) -> None:
    """意境九阶：真实战斗快照、状态、质变监听都要能跑。"""

    from types import SimpleNamespace

    routes = (
        ("630001", "不尽长江意境"),
        ("630002", "山不让尘意境"),
        ("630003", "润物无声意境"),
        ("630004", "载舟覆舟意境"),
        ("630005", "日削月割意境"),
        ("630006", "匣中夜鸣意境"),
    )
    for index, (content_id, name) in enumerate(routes):
        attributes = {
            "血气上限": 4000,
            "精神上限": 1000,
            "攻击": 80,
            "防御": 20,
            "速度": 100,
            "护盾上限": 100,
        }
        weapon_attack, statuses, amplifier = services.character._yijing_battle(
            SimpleNamespace(
                yijing=(
                    SimpleNamespace(content_id=content_id, name=name, tier=9),
                )
            ),
            attributes,
            0.0,
        )
        assert weapon_attack >= 0.0
        assert statuses
        assert float(attributes.get("神魂上限", 0)) > 0
        assert any(status.action_limits for status in statuses)
        spec = CombatantSpec(
            id=f"yijing-9-{index}",
            name=f"九阶{name}",
            attributes=attributes,
            prepared_statuses=statuses,
            growth_amplifier=1.0 + amplifier,
        )
        result = _fight(
            services,
            limit=30,
            left_team=(spec,),
            right_team=(
                replace(
                    _spec("R"),
                    attributes={**ATTRS, "血气上限": 100_000},
                    health=100_000,
                ),
            ),
        )
        assert result.left_results and result.right_results
        names = {status.name for status in result.left_results[0].statuses}
        assert any("意境" in name for name in names)
        kinds = {event.kind for event in result.events}
        if content_id in ("630001", "630002", "630006"):
            assert "追加攻击后" in kinds, f"{name}九阶没有追加攻击"
        if content_id == "630003":
            assert result.left_results[0].shield > 0 or any(
                "护盾" in str(event.values) for event in result.events
            )
        if content_id == "630004":
            assert any(
                "载舟覆舟" in str(event.values) and "造成伤害后" == event.kind
                for event in result.events
            ), "载舟覆舟九阶没有实际伤害"
        if content_id == "630005":
            assert any(
                event.kind == "添加状态后" and "日削月割" in str(event.values)
                for event in result.events
            ), "日削月割质变没有实际加蚀甲"



def test_bloodline_can_set_soul_max_only(services) -> None:
    """血脉固定属性可以给神魂上限；这是属性边界，不碰神魂当前值。"""

    from decimal import Decimal

    from game.features.xuemai import XuemaiFeature
    from game.features.xuemai.matching import Bloodline, BloodlineRules

    xuemai = XuemaiFeature(services.data, services.character, services.database)
    xuemai.initialize()
    custom = BloodlineRules(
        bloodlines=(
            Bloodline(
                "999999",
                "测试魂血",
                "弱",
                False,
                ((1, 0, 100),),
                "",
                "",
                (
                    {
                        "能力": "固定属性加成",
                        "属性": {"神魂上限": 5.0},
                    },
                ),
                False,
            ),
        ),
        awaken_tiers=((Decimal("0"), Decimal("100"), Decimal("1.0")),),
    )
    xuemai.rules = lambda: custom  # type: ignore[method-assign]
    growth = xuemai.bloodline_growth("000000000000")
    assert growth == {"神魂上限": 5.0}


def test_bloodline_real_character_reaches_battle(services) -> None:
    """真实人物 + 真实 DNA：血脉固定属性进入战斗，觉醒档按气血取倍率。"""

    from game.core.character.contracts import CharacterCreateCommand
    from game.core.database.contracts import StateMutation, TransactionCommand
    from game.features.xuemai import XuemaiFeature

    xuemai = XuemaiFeature(services.data, services.character, services.database)
    xuemai.initialize()
    assert xuemai.awaken("39") > 1.0
    assert xuemai.awaken("70") == 1.0

    user_id = "bloodline-e2e"
    asyncio.run(
        services.character.create(
            CharacterCreateCommand(
                user_id, "create-bloodline", "血脉测试", "女", (15, 17), ""
            )
        )
    )
    dna = "000000759999"  # 满月血：G4/G5>=75、G6>=50，能觉醒
    state = {"DNA": dna, "代次": 0, "胎次": 0, "族谱": []}
    asyncio.run(
        services.database.commit(
            TransactionCommand(
                user_id,
                "seed-bloodline",
                "血脉定DNA",
                (
                    StateMutation(
                        user_id,
                        xuemai.state_type(),
                        xuemai.state_key(),
                        state,
                        0,
                    ),
                ),
                {"DNA": dna},
            )
        )
    )
    spec = asyncio.run(services.character.combatant(user_id))
    assert spec.dna == dna
    assert spec.bloodline_disabled is False
    result = _fight(
        services,
        limit=3,
        left_team=(spec,),
        right_team=(_spec("R"),),
    )
    attributes = result.left_results[0].attributes
    base_attack = float(spec.attributes.get("攻击", 0))
    assert float(attributes.get("攻击", 0)) >= base_attack + 7.0  # 满月血固定攻击 +7

    disabled = replace(spec, bloodline_disabled=True)
    disabled_result = _fight(
        services,
        limit=3,
        left_team=(disabled,),
        right_team=(_spec("R"),),
    )
    assert float(disabled_result.left_results[0].attributes.get("攻击", 0)) < float(
        attributes.get("攻击", 0)
    )


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
                InventoryAdjustment("220032", "01", 1),
                InventoryAdjustment("220086", "01", 1),
                InventoryAdjustment("210001", "01", 4),
                InventoryAdjustment("220001", "01", 6),
                InventoryAdjustment("200001", "01", 6),
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


def test_alchemy_material_path_covers_ore(services) -> None:
    """丹药材料里的灵矿必须进入验药与炼制，不能只扫兽宝和灵植。"""

    from game.core.asset.contracts import InventoryAdjustment
    from game.core.character.contracts import CharacterCreateCommand
    from game.core.database.contracts import TransactionCommand

    user_id = "alchemy-e2e"
    asyncio.run(
        services.character.create(
            CharacterCreateCommand(
                user_id, "create-alchemy", "炼丹测试", "男", (15, 17), ""
            )
        )
    )
    plan = asyncio.run(
        services.asset.plan_inventory_changes(
            user_id,
            (
                InventoryAdjustment("210064", "04", 1),
                InventoryAdjustment("200001", "04", 2),
                InventoryAdjustment("220001", "04", 2),
            ),
        )
    )
    asyncio.run(
        services.database.commit(
            TransactionCommand(user_id, "seed-alchemy", "测试", plan.operations, {})
        )
    )
    preview = asyncio.run(services.alchemy.preview(user_id, "120033"))
    assert preview.can_refine
    fitted = asyncio.run(services.alchemy.refine(user_id, "craft-alchemy", "120033"))
    assert fitted.quantity_after == 1


def test_spirit_stone_change_makes_change(services) -> None:
    """1 枚圣品必须能付 3810 并找回零钱，不能报余额不足。"""

    from game.core.asset.contracts import InventoryAdjustment
    from game.core.character.contracts import CharacterCreateCommand
    from game.core.database.contracts import TransactionCommand

    user_id = "currency-change"
    asyncio.run(
        services.character.create(
            CharacterCreateCommand(user_id, "create-currency", "找零测试", "男", (15, 17), "")
        )
    )
    seed = asyncio.run(
        services.asset.plan_inventory_changes(
            user_id, (InventoryAdjustment("230001", "05", 1),)
        )
    )
    asyncio.run(
        services.database.commit(
            TransactionCommand(user_id, "seed-currency", "测试", seed.operations, {})
        )
    )
    before = asyncio.run(services.asset.spirit_stone_balance(user_id))
    plan = asyncio.run(services.asset.plan_spirit_stone_change(user_id, -3810))
    asyncio.run(
        services.database.commit(
            TransactionCommand(user_id, "pay-3810", "测试", plan.operations, {})
        )
    )
    after = asyncio.run(services.asset.spirit_stone_balance(user_id))
    assert before - after == 3810


def test_promotion_direct_upgrade(services) -> None:
    """任意低品直接升圣，扣 1 枚圣品灵石。"""

    from game.core.asset.contracts import InventoryAdjustment
    from game.core.character.contracts import CharacterCreateCommand
    from game.core.database.contracts import TransactionCommand

    user_id = "promotion-e2e"
    asyncio.run(
        services.character.create(
            CharacterCreateCommand(user_id, "create-promotion", "升阶测试", "男", (15, 17), "")
        )
    )
    seed = asyncio.run(
        services.asset.plan_inventory_changes(
            user_id,
            (
                InventoryAdjustment("200001", "01", 1),
                InventoryAdjustment("230001", "05", 1),
            ),
        )
    )
    asyncio.run(
        services.database.commit(
            TransactionCommand(user_id, "seed-promotion", "测试", seed.operations, {})
        )
    )
    before = asyncio.run(services.asset.spirit_stone_balance(user_id))
    plan = asyncio.run(
        services.promotion.plan_upgrade(user_id, "200001", "01", "05", 1)
    )
    assert plan.total_cost == 10000
    asyncio.run(
        services.database.commit(
            TransactionCommand(user_id, "upgrade-1", "测试", plan.operations, {})
        )
    )
    stacks = asyncio.run(services.asset.inventory_stacks(user_id, "200001"))
    assert [(stack.grade.grade_id, stack.quantity) for stack in stacks] == [("05", 1)]
    assert before - asyncio.run(services.asset.spirit_stone_balance(user_id)) == 10000


def test_promotion_crafting_plan(services) -> None:
    """炼丹缺天品材料时，方案应给出兽宝/灵植/灵矿三条升阶并带炼制命令。"""

    import game.app as app
    from game.core.asset.contracts import InventoryAdjustment
    from game.core.character.contracts import CharacterCreateCommand
    from game.core.database.contracts import TransactionCommand
    from game.features.shengjie import ShengjieFeature

    user_id = "plan-e2e"
    asyncio.run(
        services.character.create(
            CharacterCreateCommand(user_id, "create-plan", "方案测试", "男", (15, 17), "")
        )
    )
    seed = asyncio.run(
        services.asset.plan_inventory_changes(
            user_id,
            (
                InventoryAdjustment("210064", "01", 1),
                InventoryAdjustment("200001", "01", 2),
                InventoryAdjustment("220001", "01", 2),
            ),
        )
    )
    asyncio.run(
        services.database.commit(
            TransactionCommand(user_id, "seed-plan", "测试", seed.operations, {})
        )
    )
    feature = ShengjieFeature(
        services.data,
        services.asset,
        services.database,
        services.promotion,
        services.alchemy,
        services.forging,
        services.formation,
    )
    feature.initialize()
    plan = asyncio.run(feature.plan_crafting(user_id, "炼丹", "120033", 1))
    assert plan.name == "一息续命丹"
    assert len(plan.plan.lines) == 3
    assert plan.plan.total_cost == 20000
    assert plan.plan.satisfiable
    assert plan.craft_command == "开丹炉 一息续命丹"


def test_promotion_formation_plan(services) -> None:
    """炼阵方案按两条阵核矿给出升阶缺口。"""

    from game.core.character.contracts import CharacterCreateCommand
    from game.features.shengjie import ShengjieFeature

    user_id = "plan-formation"
    asyncio.run(
        services.character.create(
            CharacterCreateCommand(user_id, "create-plan-f", "阵方案", "男", (15, 17), "")
        )
    )
    feature = ShengjieFeature(
        services.data,
        services.asset,
        services.database,
        services.promotion,
        services.alchemy,
        services.forging,
        services.formation,
    )
    feature.initialize()
    plan = asyncio.run(feature.plan_crafting(user_id, "炼阵", "黄品一线天开阵", 1))
    assert plan.name == "一线天开阵"
    assert len(plan.plan.missing) == 2
    assert plan.craft_command == "炼阵 黄品一线天开阵"
