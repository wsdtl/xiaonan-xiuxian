"""新命令面的 handler 分支回归：缺品级不执行、目录详情只查单条。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


class _Copy:
    def __init__(self) -> None:
        self.text = {
            "错误": {
                "炼阵格式": "写法：炼阵 <品级><阵法名>",
                "写法": "写法",
                "格式": "格式",
            }
        }


class _AlchemyFeature:
    def __init__(self) -> None:
        self.preview_calls = []
        self.copy_value = SimpleNamespace()

    def copy(self):
        return self.copy_value

    async def preview(self, user_id, identifier, grade, quantity):
        self.preview_calls.append((identifier, grade, quantity))
        return object()

    @staticmethod
    def preview_actions(value):
        return ()


class _ForgingFeature:
    def __init__(self) -> None:
        self.preview_calls = []
        self.copy_value = SimpleNamespace()

    def copy(self):
        return self.copy_value

    async def preview(self, user_id, identifier):
        self.preview_calls.append(identifier)
        return object()

    @staticmethod
    def preview_actions(value):
        return ()


class _FormationFeature:
    def __init__(self) -> None:
        self.preview_calls = []
        self.form_calls = 0
        self.copy_value = _Copy()

    def copy(self):
        return self.copy_value

    @staticmethod
    def grade_prefix(value: str) -> str:
        if value in {"黄品", "黄", "01"}:
            return "黄品"
        raise ValueError(value)

    async def preview(self, user_id, identifier, grade, investments):
        self.preview_calls.append((identifier, grade, investments))
        return object()

    @staticmethod
    def preview_actions(value):
        return ()

    async def form(self, *args, **kwargs):
        self.form_calls += 1
        raise AssertionError("缺品级或目录详情不应执行炼阵")


def _services(feature, name: str):
    return SimpleNamespace(features=SimpleNamespace(**{name: feature}))


def _capture(monkeypatch, module):
    sent = []

    async def send(message, **kwargs):
        sent.append(message)
        return True

    monkeypatch.setattr(module, "send_game_reply", send)
    return sent


def test_alchemy_catalog_without_grade_returns_candidates(monkeypatch) -> None:
    from game.cmd.炼制 import 炼丹 as module

    feature = _AlchemyFeature()
    sent = _capture(monkeypatch, module)
    chosen = []

    def choose(copy, item):
        chosen.append(item)
        return object()

    monkeypatch.setattr(module, "current_game_services", lambda: _services(feature, "liandan"))
    monkeypatch.setattr(module.reply, "choose_grade", choose)
    asyncio.run(module.alchemy_catalog("u", "聚气丹", None))
    assert chosen == ["聚气丹"]
    assert feature.preview_calls == []
    assert sent


def test_alchemy_catalog_detail_checks_only_one_recipe(monkeypatch) -> None:
    from game.cmd.炼制 import 炼丹 as module

    feature = _AlchemyFeature()
    sent = _capture(monkeypatch, module)

    def preview(copy, value, actions):
        return object()

    monkeypatch.setattr(module, "current_game_services", lambda: _services(feature, "liandan"))
    monkeypatch.setattr(module.reply, "preview", preview)
    asyncio.run(module.alchemy_catalog("u", "黄品聚气丹", None))
    assert feature.preview_calls == [("聚气丹", "黄品", 1)]
    assert sent


def test_forging_catalog_detail_checks_only_one_law(monkeypatch) -> None:
    from game.cmd.炼制 import 炼器 as module

    feature = _ForgingFeature()
    sent = _capture(monkeypatch, module)

    def preview(copy, value, actions):
        return object()

    monkeypatch.setattr(module, "current_game_services", lambda: _services(feature, "lianqi"))
    monkeypatch.setattr(module.reply, "preview", preview)
    asyncio.run(module.forging_catalog("u", "玄品无归劫锋", None))
    assert feature.preview_calls == ["玄品无归劫锋"]
    assert sent


def test_formation_root_without_grade_returns_candidates(monkeypatch) -> None:
    from game.cmd.炼制 import 炼阵 as module

    feature = _FormationFeature()
    _capture(monkeypatch, module)
    chosen = []
    monkeypatch.setattr(module, "current_game_services", lambda: _services(feature, "lianzhen"))
    monkeypatch.setattr(module.reply, "choose_grade", lambda copy, identifier: chosen.append(identifier) or object())
    asyncio.run(module.formation_root("u", "叠翠盘根阵", SimpleNamespace(request_id="r"), None))
    assert chosen == ["叠翠盘根阵"]
    assert feature.preview_calls == []
    assert feature.form_calls == 0


def test_formation_catalog_detail_checks_only_one_formation(monkeypatch) -> None:
    from game.cmd.炼制 import 炼阵 as module

    feature = _FormationFeature()
    sent = _capture(monkeypatch, module)
    monkeypatch.setattr(module, "current_game_services", lambda: _services(feature, "lianzhen"))
    monkeypatch.setattr(module.reply, "preview", lambda copy, value, actions: object())
    asyncio.run(module.formation_catalog("u", "黄品叠翠盘根阵", None))
    assert feature.preview_calls == [("叠翠盘根阵", "黄品", None)]
    assert feature.form_calls == 0
    assert sent
