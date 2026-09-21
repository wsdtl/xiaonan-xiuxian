"""突破丹必须由丹药核心解析——基础物品目录里根本没有丹药这一类。

这条路径曾经整条不可用：突破走的是基础物品目录，而那个目录只索引兽宝、灵植、灵矿，
于是**任何**突破丹都会回「未找到物品：聚气丹」，玩家炼出了丹也突破不了。
判别方式就是「丹药住在哪个目录里」：丹药核心认，基础物品目录不认，两者不能混用。
"""

from __future__ import annotations

import pytest

from game.app import build_game_services
from game.core.item_catalog import ItemNotFoundError
from game.features.renwu_peiyang import CharacterCultivationFeatureError

聚气丹 = "140001"


@pytest.fixture
def services():
    value = build_game_services()
    try:
        yield value
    finally:
        value.core.database.close()


def test_丹药只住在丹药核心(services) -> None:
    assert services.core.medicine.resolve("聚气丹") == 聚气丹
    assert services.core.medicine.resolve(聚气丹) == 聚气丹
    with pytest.raises(ItemNotFoundError):
        services.core.item_catalog.inspect("聚气丹")


def test_突破按丹药核心解析编号与名称(services) -> None:
    feature = services.features.renwu_peiyang
    assert feature._resolve_medicine("聚气丹") == 聚气丹
    assert feature._resolve_medicine(聚气丹) == 聚气丹
    assert feature._medicine_name(聚气丹) == "聚气丹"


def test_突破拿不到的丹报错说清楚(services) -> None:
    feature = services.features.renwu_peiyang
    with pytest.raises(CharacterCultivationFeatureError) as error:
        feature._resolve_medicine("不存在的丹药")
    assert "丹药" in str(error.value)
