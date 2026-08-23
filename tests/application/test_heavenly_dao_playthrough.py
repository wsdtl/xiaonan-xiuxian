from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path

import game.app as game_app
from game.cmd.command import registered_commands
from game.config import GameConfig, GameDatabaseConfig
from launch.adapter.local import LocalEventHandler, dispatch
from main import create_app

HEAVENLY_DAO_ID = "system.heavenly_dao"
LOCAL_ACCOUNTS = (
    ("heavenly-dao-a", "甲田", "男"),
    ("heavenly-dao-b", "乙甲", "女"),
)
BRANCH_ACCOUNT = ("heavenly-dao-c", "丙柳", "男")

# 每个命令都使用一条具有业务含义的调用。成功主流程由下面的多人试玩先走；
# 依赖尚未取得的物资、道侣、宗门或战书时，允许返回明确的业务拒绝。
COMMAND_INVOCATIONS = {
    "帮助": "帮助 角色",
    "创建人物": "创建人物 重复人物 男",
    "人物": "人物",
    "查看道侣": "查看道侣",
    "交谈": "交谈 顾听澜",
    "赠予": "赠予 顾听澜 赤阳花 01 1",
    "邀约": "邀约 顾听澜",
    "暂别": "暂别 顾听澜",
    "夺元": "夺元",
    "人物培养": "人物培养",
    "人物装配": "人物装配 真意 410089 01 1",
    "人物突破": "人物突破 小境破障丹",
    "人物覆炼": "人物覆炼 太白惊鸿 1",
    "先天灵宝": "先天灵宝 1",
    "道侣培养": "道侣培养",
    "执掌灵宝": "执掌灵宝 太虚镜",
    "道侣突破": "道侣突破 小境破障丹",
    "道侣覆炼": "道侣覆炼 太白惊鸿 1",
    "人物服丹": "人物服丹 小还丹 01",
    "道侣服丹": "道侣服丹 小还丹 01",
    "人药": "人药 开",
    "侣药": "侣药 开",
    "去": "去 丹霞城",
    "开始探险": "开始探险",
    "探险进度": "探险进度",
    "探险结束": "探险结束 1",
    "开始闭关": "开始闭关",
    "闭关进度": "闭关进度",
    "闭关结束": "闭关结束 1",
    "开始讨伐": "开始讨伐",
    "讨伐战况": "讨伐战况",
    "讨伐结束": "讨伐结束",
    "队伍": "队伍",
    "宗门": "宗门",
    "宗门同行": "宗门同行",
    "开始采药": "开始采药",
    "采药进度": "采药进度",
    "采药结束": "采药结束 1",
    "开始采矿": "开始采矿",
    "采矿进度": "采矿进度",
    "采矿结束": "采矿结束 1",
    "托管": "托管 探险 闭关",
    "继续托管": "继续托管",
    "取消托管": "取消托管",
    "入山门": "入山门",
    "出山门": "出山门",
    "灵藏": "灵藏 灵植 1",
    "捐藏": "捐藏 赤阳花 01 1",
    "万珍殿": "万珍殿 丹药 1",
    "灵脉": "灵脉",
    "捐珍": "捐珍 小还丹 01 1",
    "灵田": "灵田",
    "发珍": "发珍 天道 小还丹 01 1",
    "藏经阁": "藏经阁 1",
    "借阅功法": "借阅功法 青元诀 01",
    "地图": "地图",
    "位置": "位置",
    "附近": "附近 修士 1",
    "宗门约战": "约战 赤霄宗 100",
    "接战": "接战",
    "拒战": "拒战",
    "撤战": "撤战",
    "锁阵": "锁阵",
    "解阵": "解阵",
    "开战": "开战",
    "停战": "停战",
    "战况": "战况",
    "战录": "战录 1",
    "布阵": "布阵 530001:01",
    "切磋": "切磋 甲田",
    "接受切磋": "接受切磋",
    "拒绝切磋": "拒绝切磋",
    "炼器": "炼器 太白惊鸿",
    "开炉": "开炉 太白惊鸿",
    "炼丹": "炼丹 小还丹",
    "开丹炉": "开丹炉 小还丹",
    "阵法": "阵法 周天星斗大阵 黄",
    "炼阵": "炼阵 周天星斗大阵 黄",
    "归元": "归元 功法",
    "补天": "补天 人物",
    "易形": "易形",
    "百炼堂": "百炼堂 灵器",
    "丹鼎阁": "丹鼎阁 恢复丹",
    "演阵台": "演阵台 1",
    "纳戒": "纳戒",
    "查看": "查看 小还丹",
    "交易": "交易 真意 1",
    "购买": "购买 410089 01 1",
    "赠送": "赠送 甲田 灵石 1",
    "天道后台": "天道后台",
}


def _run(awaitable):
    return asyncio.run(awaitable)


def test_heavenly_dao_drives_every_command_and_multiplayer_flow(
    tmp_path: Path, monkeypatch
) -> None:
    """天道后台主号带两个本地小号跑通全部命令和多人活动边界。"""

    monkeypatch.setattr(
        game_app,
        "game_config",
        GameConfig(
            GameDatabaseConfig(
                tmp_path / "game.db",
                tmp_path / "runtime.db",
                5000,
            )
        ),
    )
    console_module = import_module("game.cmd.后台.天道后台.console")
    console_runtime = import_module("game.cmd.后台.天道后台.runtime")
    console_site = import_module("game.cmd.后台.天道后台.site")
    hosting_runtime = import_module("game.cmd.通用.托管.runtime")
    storage_module = import_module("game.cmd.后台.天道后台.storage")
    temporary_console = console_module.MessageConsoleService(
        storage_module.MessageFlowStore(
            tmp_path / "console.db",
            retention_seconds=console_module.RETENTION_SECONDS,
            busy_timeout_ms=5000,
        ),
        media_dir=tmp_path / "console-media",
    )
    monkeypatch.setattr(console_module, "service", temporary_console)
    monkeypatch.setattr(console_runtime, "service", temporary_console)
    monkeypatch.setattr(console_site, "service", temporary_console)
    monkeypatch.setattr(hosting_runtime, "schedule_plan", lambda _session: None)
    monkeypatch.setattr(hosting_runtime, "cancel_plan", lambda _session_id: None)

    _run(_exercise_everything(temporary_console))


async def _exercise_everything(heavenly_console) -> None:
    covered: set[str] = set()
    sequence = 0

    async def heavenly(raw_message: str, *expected: str):
        nonlocal sequence
        sequence += 1
        result = await heavenly_console.dispatch(raw_message)
        return _assert_result(result, raw_message, covered, expected)

    async def local(user_id: str, raw_message: str, *expected: str):
        nonlocal sequence
        sequence += 1
        result = await dispatch(
            user_id=user_id,
            raw_message=raw_message,
            sender_name=user_id,
            event_id=f"heavenly-play-{sequence:04d}",
        )
        return _assert_result(result, raw_message, covered, expected)

    app = create_app()
    async with app.router.lifespan_context(app):
        await LocalEventHandler.run()

        await heavenly("创建人物 天道 男", "人物创建完成")
        for user_id, name, gender in LOCAL_ACCOUNTS:
            await local(user_id, f"创建人物 {name} {gender}", "人物创建完成")
        await local(
            BRANCH_ACCOUNT[0],
            f"创建人物 {BRANCH_ACCOUNT[1]} {BRANCH_ACCOUNT[2]}",
            "人物创建完成",
        )

        await heavenly("帮助", "当前已经开放的命令")
        await heavenly("人物", "当前状态")
        await heavenly("地图", "全境舆图")
        await heavenly("位置", "可用功能")
        await heavenly("附近 修士", "附近")

        # 主号发起邀请，小号必须各自从普通本地驱动接受。
        await heavenly("队伍 邀请 甲田", "邀请")
        await local("heavenly-dao-a", "队伍 接受", "加入")
        await heavenly("队伍 邀请 丙柳", "邀请")
        await local(BRANCH_ACCOUNT[0], "队伍 拒绝", "拒绝")
        await heavenly("队伍 邀请 乙甲", "邀请")
        await local("heavenly-dao-b", "队伍 接受", "加入")
        team_page = await heavenly("队伍", "天道", "甲田", "乙甲")
        assert "3" in team_page.content

        # 队伍管理的权限、目标和重复关系分支不能只靠主流程命中。
        await heavenly("队伍 邀请 system.heavenly_dao", "同处修士中没有找到该角色")
        await heavenly("队伍 邀请 乙甲", "对方已经在队伍中")
        await local("heavenly-dao-a", "队伍 邀请 丙柳", "只有队长可以执行该操作")
        await local("heavenly-dao-a", "队伍 移交 天道", "只有队长可以执行该操作")
        await heavenly("队伍 请离 不存在的人", "该修士不在你的队伍中")

        await heavenly("去 丹霞城", "抵达", "丹霞城")
        for user_id, _, _ in LOCAL_ACCOUNTS:
            await local(user_id, "位置", "丹霞城")
        await local(BRANCH_ACCOUNT[0], "去 丹霞城", "抵达", "丹霞城")

        services = game_app.current_game_services()
        await heavenly("采药", "入山采药", "同行用户: 3")
        await heavenly("开始采药", "正在带领同行修士采药", "采药进度")
        await local("heavenly-dao-a", "采药进度", "领队")
        await _finish_activity(
            services,
            HEAVENLY_DAO_ID,
            "gathering_session",
            "最晚结束时间",
            services.features.caiyao,
            "heavenly-settle-herbs",
        )
        await heavenly("采药结束", "采药总结", "6/6")

        await heavenly("采矿", "勘脉采矿", "同行用户: 3")
        await local("heavenly-dao-b", "采矿进度", "领队")
        await _finish_activity(
            services,
            HEAVENLY_DAO_ID,
            "gathering_session",
            "最晚结束时间",
            services.features.caikuang,
            "heavenly-settle-ore",
        )
        await heavenly("采矿结束", "采矿总结", "6/6")

        await heavenly("开始闭关", "入定闭关", "同行修士: 3")
        await local("heavenly-dao-a", "闭关进度", "领队")
        await _finish_activity(
            services,
            HEAVENLY_DAO_ID,
            "retreat_session",
            "最晚出关时间",
            services.features.biguan,
            "heavenly-settle-retreat",
        )
        await heavenly("闭关结束", "闭关总结", "6/6")

        await heavenly("开始探险", "探险启程", "同行修士: 3")
        await local("heavenly-dao-b", "探险进度", "探险尚未结束")
        await _finish_activity(
            services,
            HEAVENLY_DAO_ID,
            "exploration_session",
            "结束时间",
            services.features.tanxian,
            "heavenly-settle-exploration",
        )
        await heavenly("探险结算", "探险总结")

        await heavenly("托管 探险 闭关", "托管")
        await local("heavenly-dao-a", "人物", "托管")
        await heavenly("取消托管", "取消")

        # 完整走过移交、请离、成员主动离开和新队长解散。
        await heavenly("队伍 移交 甲田", "移交")
        await local("heavenly-dao-a", "队伍 请离 乙甲", "已请乙甲离开队伍")
        await local("heavenly-dao-a", "队伍 邀请 丙柳", "邀请")
        await local(BRANCH_ACCOUNT[0], "队伍 接受", "加入")
        await heavenly("队伍 离开", "离开")
        await local("heavenly-dao-a", "队伍 解散", "解散")

        # 地点专属功能必须走到实际页面，而不是只在后面的账本里命中命令词。
        await heavenly("交易", "交易")
        await heavenly("炼器", "器律")
        await heavenly("阵法", "阵法")
        await heavenly("去 丹泉苑", "抵达", "丹泉苑")
        await heavenly("炼丹", "丹方")
        await heavenly("去 丹霞城", "抵达", "丹霞城")

        # 宗门关系、山门空间、宗门设施和宗门同行走一条成功链路。
        await heavenly("宗门 创建 天道宗", "天道宗")
        await heavenly("宗门 邀请 丙柳", "邀请")
        await local(BRANCH_ACCOUNT[0], "宗门 拒绝", "拒绝")
        await heavenly("宗门 邀请 甲田", "邀请")
        await local("heavenly-dao-a", "宗门 接受", "已加入天道")
        await heavenly("宗门 邀请 乙甲", "邀请")
        await local("heavenly-dao-b", "宗门 接受", "已加入天道")
        await heavenly("宗门", "天道宗", "甲田", "乙甲")
        await heavenly("宗门 邀请 甲田", "对方已经加入其他宗门")
        await local("heavenly-dao-a", "宗门 任命长老 乙甲", "只有宗主可以执行该操作")
        await heavenly("宗门 任命长老 甲田", "升任本宗长老")
        await heavenly("宗门 罢免长老 甲田", "退为本宗弟子")
        await heavenly("宗门 任命长老 甲田", "升任本宗长老")
        await local("heavenly-dao-a", "宗门 逐出 天道", "不能对宗主执行该操作")
        await heavenly("宗门 逐出 不存在的人", "该修士不在你的宗门中")
        await heavenly("宗门 退出", "宗主必须先转让宗主之位")
        await heavenly("入山门", "进入")
        await local("heavenly-dao-a", "入山门", "进入")
        await local("heavenly-dao-b", "入山门", "进入")
        await heavenly("灵藏", "灵藏")
        await heavenly("万珍殿", "万珍殿")
        await heavenly("藏经阁", "藏经阁")
        await heavenly("百炼堂", "百炼堂")
        await heavenly("丹鼎阁", "丹鼎阁")
        await heavenly("演阵台", "演阵台")
        await heavenly("灵脉", "灵脉")
        await heavenly("灵田", "灵田")
        await heavenly("宗门同行 召集", "召集")
        await local("heavenly-dao-a", "宗门同行 加入", "加入")
        await local("heavenly-dao-b", "宗门同行 加入", "加入")
        await local("heavenly-dao-a", "宗门同行 召集", "只有宗主可以召集")
        await heavenly("宗门同行 请离 不存在的人", "该修士不在本次宗门同行中")
        await local("heavenly-dao-b", "宗门同行 离开", "已经离开本次宗门同行")
        await local("heavenly-dao-b", "宗门同行 加入", "加入")
        await heavenly("宗门同行 请离 乙甲", "已请乙甲离开本次同行")
        await local("heavenly-dao-b", "宗门同行 加入", "加入")
        await heavenly("宗门同行", "同行")
        await heavenly("宗门同行 解散", "本次宗门同行已经解散")
        await heavenly("出山门", "已出山门")

        # 完整走过逐出、宗主转让、原宗主退出和新宗主解散。
        await heavenly("宗门 逐出 乙甲", "已将乙甲逐出宗门")
        await heavenly("宗门 转让 甲田", "已将宗主之位转让给甲田")
        await heavenly("宗门 退出", "已退出宗门")
        await local("heavenly-dao-a", "宗门 解散", "宗门已经解散")

        # 非法品级必须作为业务错误回复，不能让资产层异常穿透命令入口。
        await heavenly("人物服丹 小还丹 不存在", "未知物品品级")
        await local("heavenly-dao-a", "队伍 接受", "当前没有待处理的队伍邀请")
        await local("heavenly-dao-a", "队伍 离开", "当前未加入队伍")
        await heavenly("队伍 解散", "当前未加入队伍")

        # 对尚未被成功主流程触达的命令逐条发送有效形态的业务文本。
        await heavenly("去 镇北军镇", "抵达", "镇北军镇")
        await heavenly("讨伐", "讨伐启阵")
        await heavenly("讨伐战况", "讨伐战况")
        await _finish_activity(
            services,
            HEAVENLY_DAO_ID,
            "raid_session",
            "结束时间",
            services.features.taofa,
            "heavenly-settle-raid",
        )
        await heavenly("讨伐结束", "讨伐结算")
        await heavenly("去 丹霞城", "抵达", "丹霞城")
        for command, invocation in COMMAND_INVOCATIONS.items():
            if command in covered:
                continue
            await heavenly(invocation)

        registered = {command for command, _, _ in registered_commands()}
        assert set(COMMAND_INVOCATIONS) == registered
        assert covered == registered

    # 重新装配组合根，确认三个角色、位置、队伍解散结果和资产都来自数据库。
    restarted = create_app()
    async with restarted.router.lifespan_context(restarted):
        await LocalEventHandler.run()
        await heavenly("人物", "天道", "丹霞城")
        await heavenly("纳戒", "物品")
        for user_id, name, _ in LOCAL_ACCOUNTS:
            await local(user_id, "人物", name, "丹霞城")
            await local(user_id, "队伍", "当前未加入队伍")


async def _finish_activity(
    services,
    user_id: str,
    state_type: str,
    end_key: str,
    feature,
    request_id: str,
) -> None:
    sessions = await services.core.database.list_for_user(
        user_id, state_type=state_type
    )
    assert sessions, state_type
    end_at = datetime.fromisoformat(str(sessions[-1].value[end_key]))
    result = await feature.settle(
        user_id, request_id, now=end_at + timedelta(seconds=1)
    )
    assert result.replayed is False


def _assert_result(result, raw_message: str, covered: set[str], expected) -> object:
    command = raw_message.split(maxsplit=1)[0]
    assert result.matched, raw_message
    assert result.matched_count == 1, raw_message
    assert len(result.replies) == 1, raw_message
    message = result.replies[0].message
    content = message.content
    assert content.strip(), raw_message
    assert "状态检查失败，请稍后重试" not in content, raw_message
    assert "游戏微服务尚未初始化" not in content, raw_message
    assert "Traceback" not in content, raw_message
    assert "格式不正确" not in content, raw_message
    assert "参数格式错误" not in content, raw_message
    for value in expected:
        assert value in content, (raw_message, content)
    from game.cmd.help_registry import help_registry

    entry = help_registry.find(command)
    covered.add(entry.command if entry is not None else command)
    return message
