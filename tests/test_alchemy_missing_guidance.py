"""炼丹缺料要说清「缺什么品级」。

原来只写「药引 · 兽宝 × 1」，玩家纳戒里明明有兽宝却不知道为什么不能用——
真正的原因是品级不够（难度 2 起药引要玄品以上，难度 4 起辅材也要地品以上）。
这条链路一路试玩到第四境才踩到，属于「不说人话」的典型，所以钉在自测里。
"""

from __future__ import annotations

import json
from pathlib import Path

from game.app import build_game_services

DATA = Path(__file__).resolve().parents[1] / "data"
难度二丹 = "140029"  # 凝海丹：难度 2，药引要玄品以上（周天丹已按负责人定案降档，不再适合做样例）
难度一丹 = "140001"  # 聚气丹：难度 1，黄品即可


def _炉法药脉(丹编号: str, services) -> list[str]:
    recipe = next(
        value for value in services.core.alchemy.recipes("突破丹") if value.medicine_id == 丹编号
    )
    炉法 = {
        x["名称"]: x["辅材"]
        for x in json.loads((DATA / "物品" / "炼丹" / "规则" / "炉法.json").read_text(encoding="utf-8"))
    }
    return [x["药脉"] for x in 炉法[recipe.method]]


def _本脉灵植(脉: str) -> str:
    归脉 = json.loads((DATA / "物品" / "炼丹" / "规则" / "归脉.json").read_text(encoding="utf-8"))
    池 = next(x["灵植池"] for x in 归脉 if x["本脉"] == 脉)
    条目 = json.loads(
        (DATA / "物品" / "基础物品" / "内容" / "灵植" / f"{池}.json").read_text(encoding="utf-8")
    )
    return str((条目 if isinstance(条目, list) else [条目])[0]["编号"])


def _炉法药脉(丹编号: str, services) -> list[str]:
    recipe = next(
        value for value in services.core.alchemy.recipes("突破丹") if value.medicine_id == 丹编号
    )
    炉法 = {
        x["名称"]: x["辅材"]
        for x in json.loads((DATA / "物品" / "炼丹" / "规则" / "炉法.json").read_text(encoding="utf-8"))
    }
    return [x["药脉"] for x in 炉法[recipe.method]]


def _本脉灵植(脉: str) -> str:
    归脉 = json.loads((DATA / "物品" / "炼丹" / "规则" / "归脉.json").read_text(encoding="utf-8"))
    池 = next(x["灵植池"] for x in 归脉 if x["本脉"] == 脉)
    条目 = json.loads(
        (DATA / "物品" / "基础物品" / "内容" / "灵植" / f"{池}.json").read_text(encoding="utf-8")
    )
    return str((条目 if isinstance(条目, list) else [条目])[0]["编号"])


def test_缺料要报出要求品级() -> None:
    services = build_game_services()
    try:
        assessment = services.core.alchemy.assess(难度二丹, ())
        missing = [
            f"{item.role} · {item.trait} × {item.quantity}" for item in assessment.missing_materials
        ]
        assert any("玄品及以上兽宝" in 条目 for 条目 in missing), missing
        assert all("及以上" in 条目 for 条目 in missing), missing
    finally:
        services.core.database.close()


def test_难度一丹只要黄品() -> None:
    services = build_game_services()
    try:
        assessment = services.core.alchemy.assess(难度一丹, ())
        missing = [
            f"{item.role} · {item.trait} × {item.quantity}" for item in assessment.missing_materials
        ]
        assert any("黄品及以上兽宝" in 条目 for 条目 in missing), missing
    finally:
        services.core.database.close()


def test_缺料里带着两味辅材的名字() -> None:
    """难度二的丹要两味辅材，缺料要写明是哪两味、各要什么品级。"""

    services = build_game_services()
    try:
        脉 = _炉法药脉(难度二丹, services)
        assessment = services.core.alchemy.assess(难度二丹, ())
        文本 = " ".join(item.trait for item in assessment.missing_materials)
        for 名 in 脉:
            assert f"{名}灵植" in 文本, (名, 文本)
        assert _本脉灵植(脉[0])  # 该药脉确实有本脉灵植可取
    finally:
        services.core.database.close()
