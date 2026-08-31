from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest

from game.cmd import access_guard
from game.cmd.command import (
    COMMAND_SCOPES,
    GameCommand,
    HelpSpec,
    registered_command_routes,
    unregister_command_module,
)
from game.cmd.help_registry import help_registry
from game.core.data import JsonDataService
from game.core.item_catalog import ItemCatalogService
from game.core.player_state import StateGuardResult
from game.features.chakan_wupin import ItemInspectionFeature
from launch.adapter import (
    AdapterCapabilities,
    CommandGuardContext,
    MessageContext,
    ReplyTarget,
)
from launch.adapter.local import LocalEventHandler, dispatch
from main import create_app
from tools.架构审查.校验命令目录 import CommandLayoutError, audit_command_layout


def _run(awaitable):
    return asyncio.run(awaitable)


def _content(result) -> str:
    assert result.matched
    assert len(result.replies) == 1
    return result.replies[0].message.content


def test_loaded_commands_have_one_valid_help_declaration() -> None:
    create_app()

    assert help_registry.categories() == (
        "角色",
        "道侣",
        "修行",
        "行动",
        "世界",
        "战斗",
        "炼制",
        "资源",
    )
    assert [entry.command for entry in help_registry.entries()] == [
        "帮助",
        "创建人物",
        "人物",
        "查看道侣",
        "交谈",
        "赠予",
        "邀约",
        "暂别",
        "夺元",
        "人物培养",
        "人物装配",
        "人物突破",
        "人物覆炼",
        "先天灵宝",
        "道侣培养",
        "执掌灵宝",
        "道侣突破",
        "道侣覆炼",
        "人物服丹",
        "道侣服丹",
        "人药",
        "侣药",
        "去",
        "开始探险",
        "探险进度",
        "探险结束",
        "开始闭关",
        "闭关进度",
        "闭关结束",
        "队伍",
        "宗门",
        "宗门同行",
        "开始讨伐",
        "开始采药",
        "讨伐战况",
        "采药进度",
        "讨伐结束",
        "采药结束",
        "开始采矿",
        "采矿进度",
        "采矿结束",
        "托管",
        "继续托管",
        "取消托管",
        "入山门",
        "出山门",
        "灵藏",
        "捐藏",
        "万珍殿",
        "灵脉",
        "捐珍",
        "灵田",
        "发珍",
        "藏经阁",
        "借阅功法",
        "地图",
        "位置",
        "附近",
        "宗门约战",
        "接战",
        "拒战",
        "撤战",
        "锁阵",
        "解阵",
        "开战",
        "停战",
        "战况",
        "战录",
        "布阵",
        "切磋",
        "接受切磋",
        "拒绝切磋",
        "炼器",
        "开炉",
        "炼丹",
        "开丹炉",
        "阵法",
        "炼阵",
        "归元",
        "补天",
        "易形",
        "百炼堂",
        "丹鼎阁",
        "演阵台",
        "纳戒",
        "查看",
        "交易",
        "购买",
        "赠送",
    ]
    assert help_registry.find("web") is None
    assert help_registry.find("天道后台") is None
    assert "查看物品" not in {route for route, _, _ in registered_command_routes()}
    with pytest.raises(TypeError):
        GameCommand.fullmatch("缺少说明", scope="通用")
    with pytest.raises(ValueError, match="最多四个字"):
        GameCommand.fullmatch(
            "超过四字命令",
            scope="通用",
            guard_rule="始终可用",
            help=HelpSpec(category="世界", summary="测试", usage=("超过四字命令",)),
        )
    with pytest.raises(ValueError, match="不能同时"):
        GameCommand.fullmatch(
            "重复声明",
            scope="通用",
            guard_rule="始终可用",
            help=HelpSpec("角色", "测试命令", ("重复声明",)),
            hidden=True,
        )
    with pytest.raises(ValueError, match="后台命令必须"):
        GameCommand.fullmatch(
            "后台错",
            scope="后台",
            guard_rule="始终可用",
            help=HelpSpec("角色", "不应公开", ("后台错",)),
        )


def test_command_module_can_replace_and_unload_all_driver_registrations() -> None:
    module_name = "game.cmd.通用.热重启测试"

    async def old_callback() -> None:
        return None

    async def new_callback() -> None:
        return None

    old_callback.__module__ = module_name
    new_callback.__module__ = module_name
    decorator = GameCommand.command(
        "热测",
        aliases=("热重启测试", "重启测试"),
        scope="通用",
        guard_rule="始终可用",
        help=HelpSpec("行动", "验证模块替换", ("热测", "热重启测试")),
    )
    decorator(old_callback)
    decorator(new_callback)

    from launch.adapter.qq.handler import _command_registry

    assert len(LocalEventHandler.command_rules["热测"]) == 1
    assert len(LocalEventHandler.command_rules["热重启测试"]) == 1
    assert len(LocalEventHandler.command_rules["重启测试"]) == 1
    assert len(_command_registry.match("热重启测试")) == 1
    assert help_registry.find("热重启测试") is not None
    assert help_registry.find("重启测试").command == "热测"

    _run(LocalEventHandler.run())
    alias_result = _run(
        dispatch(
            user_id="alias-user",
            raw_message="重启测试 参数",
            sender_name="测试",
            event_id="alias-route",
        )
    )
    assert alias_result.matched is True

    unregister_command_module(module_name)

    assert "热测" not in LocalEventHandler.command_rules
    assert "热重启测试" not in LocalEventHandler.command_rules
    assert "重启测试" not in LocalEventHandler.command_rules
    assert _command_registry.match("热重启测试") == []
    assert _command_registry.match("重启测试") == []
    assert help_registry.find("热重启测试") is None


def test_command_layout_tool_checks_scope_and_managed_directory() -> None:
    create_app()

    from game.cmd.command import registered_commands

    entries = audit_command_layout(registered_commands(), scopes=COMMAND_SCOPES)
    assert {scope for _, scope, _ in entries} == {"通用", "专属", "后台"}
    with pytest.raises(CommandLayoutError, match="命令范围不一致"):
        audit_command_layout(
            (("错放命令", "专属", "game.cmd.通用.测试"),),
            scopes=COMMAND_SCOPES,
        )
    with pytest.raises(CommandLayoutError, match="不在受管目录"):
        audit_command_layout(
            (("游离命令", "通用", "game.cmd.测试"),),
            scopes=COMMAND_SCOPES,
        )


def test_help_home_and_detail_use_real_registered_commands(monkeypatch) -> None:
    create_app()
    _run(LocalEventHandler.run())

    home = _run(
        dispatch(
            user_id="help-user",
            raw_message="帮助",
            sender_name="问路人",
            event_id="help-home",
        )
    )
    assert "按分类查看当前已经开放的命令" in _content(home)
    assert "角色" in _content(home)

    detail = _run(
        dispatch(
            user_id="help-user",
            raw_message="帮助 创建人物",
            sender_name="问路人",
            event_id="help-detail",
        )
    )
    assert "建立当前账号的唯一修士人物" in _content(detail)
    assert "创建人物 姓名 性别" in _content(detail)
    assert _content(detail).startswith("**创建人物**")
    assert "**晓楠修仙**" not in _content(detail)
    assert "说明" in _content(detail)
    assert "发送:" in _content(detail)
    assert "创建人物 姓名 性别" in _content(detail)
    assert "也可发送:" in _content(detail)
    assert "结果:" in _content(detail)
    assert tuple(action.data for action in detail.replies[0].message.actions) == (
        "创建人物 ",
        "帮助 角色",
    )
    assert detail.replies[0].message.actions[0].behavior == "fill"
    assert detail.replies[0].message.actions[0].label == "填写命令"

    root = Path(__file__).resolve().parents[2]
    data = JsonDataService(root / "data")
    data.initialize()
    catalog = ItemCatalogService(data)
    catalog.initialize()
    feature = ItemInspectionFeature(catalog)
    feature.initialize()
    inspect_module = import_module("game.cmd.通用.查看")
    monkeypatch.setattr(
        inspect_module,
        "current_game_services",
        lambda: SimpleNamespace(features=SimpleNamespace(chakan_wupin=feature)),
    )
    item = _run(
        dispatch(
            user_id="help-user",
            raw_message="查看 小还丹",
            sender_name="问路人",
            event_id="inspect-item",
        )
    )
    item_content = _content(item)
    assert "小还丹" in item_content
    assert "丹药" in item_content
    assert "100005" in item_content
    assert "恢复：15%" in item_content
    assert "权重" not in item_content
    assert "参考价" not in item_content

    technique = _run(
        dispatch(
            user_id="help-user",
            raw_message="查看 400265",
            sender_name="问路人",
            event_id="inspect-technique",
        )
    )
    technique_content = _content(technique)
    assert "功法" in technique_content
    assert "400265" in technique_content
    assert "星辰借法" in technique_content
    assert "与当前目标建立“寄诀”关联" in technique_content
    assert "任意敌方行动决策前" in technique_content
    assert "保存结果" not in technique_content

    battle_medicine = _run(
        dispatch(
            user_id="help-user",
            raw_message="查看 120013",
            sender_name="问路人",
            event_id="inspect-battle-medicine",
        )
    )
    battle_medicine_content = _content(battle_medicine)
    assert "仅下一场正式战斗生效" in battle_medicine_content
    assert "暴追：" in battle_medicine_content
    assert "600013" not in battle_medicine_content
    assert "mappingproxy" not in battle_medicine_content
    assert "{'" not in battle_medicine_content

    ambiguous = _run(
        dispatch(
            user_id="help-user",
            raw_message="查看 代劫",
            sender_name="问路人",
            event_id="inspect-ambiguous",
        )
    )
    ambiguous_content = _content(ambiguous)
    assert "名称不唯一" in ambiguous_content
    assert "机制 · 代劫" in ambiguous_content
    assert "真意 · 代劫" in ambiguous_content
    assert "601288" in ambiguous_content
    assert "410013" in ambiguous_content

    removed_alias = _run(
        dispatch(
            user_id="help-user",
            raw_message="查看物品 小还丹",
            sender_name="问路人",
            event_id="inspect-removed-alias",
        )
    )
    assert not removed_alias.matched


def test_game_command_guard_uses_player_state_rule(monkeypatch) -> None:
    class FakePlayerState:
        async def authorize(self, user_id: str, rule_name: str) -> StateGuardResult:
            assert user_id == "help-user"
            assert rule_name == "仅未创建"
            return StateGuardResult(False, "已经创建人物")

    context = CommandGuardContext(
        message_context=MessageContext(
            adapter="local",
            user_id="help-user",
            request_id="help-guard",
            command="创建人物",
            message="林远 男",
            raw_message="创建人物 林远 男",
            conversation_type="private",
            reply_target=ReplyTarget("local", "help-user", "help-user", "private"),
            capabilities=AdapterCapabilities(),
        ),
        command_metadata={"game": {"guard_rule": "仅未创建"}},
    )
    monkeypatch.setattr(
        access_guard,
        "current_game_services",
        lambda: SimpleNamespace(core=SimpleNamespace(player_state=FakePlayerState())),
    )

    decision = _run(access_guard.game_access_guard(context))
    assert decision.blocked is True
