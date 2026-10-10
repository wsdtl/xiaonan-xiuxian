"""让五行可见：关系判据与数值口径（目标③）。

两件事钉住：① 关系按「主元素 对 对方主属性」判一次（原先全配对加权平均会把相生相克摊平）；
② 数值口径——无相 0.92、根性每点 0.011、夹在 0.88~1.30。

调用的是**真的** `_element_multiplier`（用一个只带 catalog 与两张关系表的桩当 self），
不重写公式——测试只摆事实，公式仍住在代码里。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from game.app import build_game_services
from game.core.combat import mechanics as mech

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _桩:
    """元素倍率只用到 catalog 与两张关系表，其余一律不碰。"""

    def __init__(self, rules: dict) -> None:
        self.catalog = type("_C", (), {"five_elements": rules})()
        self._element_generating = {row["来源"]: row["目标"] for row in rules["相生"]}
        self._element_overcoming = {row["来源"]: row["目标"] for row in rules["相克"]}


class _战斗上下文:
    element_composition_cache: dict = {}
    element_multiplier_cache: dict = {}


class _修士:
    def __init__(self, roots: dict) -> None:
        self.five_elements = roots
        self.team_synergy: dict = {}


@pytest.fixture
def rules():
    return json.loads((ROOT / "data" / "战斗" / "规则" / "五行.json").read_text(encoding="utf-8"))


@pytest.fixture
def multiply(rules):
    桩 = _桩(rules)

    def call(compositions: dict, source_roots: dict, target_roots: dict):
        return mech.AbilityRuntime._element_multiplier(
            桩, _战斗上下文(), _修士(source_roots), _修士(target_roots), {"属性构成": compositions}
        )

    return call


def test_数值口径是委托方点头的那一组(rules) -> None:
    assert rules["倍率"]["无相"] == 0.92
    assert rules["根性倍率"]["每点修正"] == 0.011
    assert rules["根性倍率"]["最低"] == 0.88
    assert rules["根性倍率"]["最高"] == 1.30


def test_相克按主元素判一次(multiply) -> None:
    # 倍率里还乘着根性项，所以这里比的是**关系之间的相对大小**：
    # 同根性下，相克最高、被克最低——这正是"不再被全配对平均摊平"的意思。
    克, 关系 = multiply({"火": 100}, {"火": 100}, {"金": 100})
    平, _ = multiply({"火": 100}, {"火": 100}, {"火": 100})
    被, _ = multiply({"火": 100}, {"火": 100}, {"水": 100})
    assert 关系 == "火 克 金"
    assert 克 > 平 > 被


def test_相生(multiply) -> None:
    _倍率, 关系 = multiply({"木": 100}, {"木": 100}, {"火": 100})
    assert 关系 == "木 生 火"


def test_被克是从攻方视角读的(multiply) -> None:
    _倍率, 关系 = multiply({"金": 100}, {"金": 100}, {"火": 100})
    assert 关系 == "金 被火克"


def test_同属性与无关都不写成关系行(multiply) -> None:
    _倍率, 关系 = multiply({"火": 100}, {"火": 100}, {"火": 100})
    assert 关系 == "火 同属"
    # 火对木才是无关（水克火，那是「被克」，不是无关）。
    _倍率, 关系 = multiply({"火": 100}, {"火": 100}, {"木": 100})
    assert 关系 == "", "无关不写关系行，不给战报添噪音"


def test_纯无相读规则里的无相倍率(multiply) -> None:
    倍率, 关系 = multiply({"无相": 100}, {"火": 100}, {"金": 100})
    assert 倍率 == 0.92, "无相不再是恒 1.0（零风险零收益会让人永远选它）"
    assert 关系 == ""


def test_根性斜率按新口径走(multiply) -> None:
    高, _ = multiply({"火": 100}, {"火": 100}, {"火": 100})
    低, _ = multiply({"火": 100}, {"火": 0}, {"火": 100})
    assert 高 > 低
    assert 0.88 <= 低 and 高 <= 1.30


def test_战报名单里有这两个键() -> None:
    body = json.loads((ROOT / "data" / "战斗" / "展示" / "战报.json").read_text(encoding="utf-8"))
    assert "五行关系" in body["展示"]["伤害事实"]
    assert "五行倍率" in body["展示"]["伤害事实"]
    assert "五行倍率" in body["标准化"]["倍率明细"]
    保留 = body["标准化"]["记录事实"]["保留"]
    assert "五行关系" in 保留 and "五行倍率" in 保留, "不在保留名单里，装载就会抛错（见 catalog.py:535）"


def test_服务能装配起来() -> None:
    services = build_game_services()
    try:
        assert services.core.combat is not None
    finally:
        services.core.database.close()
