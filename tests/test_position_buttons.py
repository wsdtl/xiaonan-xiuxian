"""位置面板只按可用功能出按钮：普通地点有采药/采矿，特殊地点没有。"""
from __future__ import annotations

from game.core.world import LocationQuery


def _labels(services, location) -> set[str]:
    actions = services.features.weizhi.position_actions(location)
    return {action.label for action in actions}


def test_normal_location_has_gather_buttons(services) -> None:
    location = services.core.world.locate(LocationQuery(location_name="溪隐台"))
    labels = _labels(services, location)
    assert {"采药", "采矿"} <= labels


def test_special_location_has_no_gather_buttons(services) -> None:
    location = services.core.world.locate(LocationQuery(location_name="坐忘台"))
    labels = _labels(services, location)
    assert any("坐忘" in label for label in labels)
    assert "采药" not in labels
    assert "采矿" not in labels


def test_sect_park_has_no_gather_buttons(services) -> None:
    location = services.core.world.locate(LocationQuery(location_name="宗门园区"))
    labels = _labels(services, location)
    assert "宗门事务" in labels
    assert "采药" not in labels
    assert "采矿" not in labels


def test_wild_has_no_location_buttons(services) -> None:
    location = services.core.world.locate(LocationQuery(xy=(0, 0)))
    assert _labels(services, location) == set()


def test_sect_park_is_gatherable(services) -> None:
    location = services.core.world.locate(LocationQuery(location_name="宗门园区"))
    assert location.plant_pool == ("灵植-溪谷",)
    assert location.mineral_pool == ("灵矿-溪谷",)
