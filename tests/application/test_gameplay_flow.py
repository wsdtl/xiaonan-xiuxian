from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import game.app as game_app
from game.config import GameConfig, GameDatabaseConfig
from game.core.database import TransactionCommand
from launch.adapter.local import LocalEventHandler, dispatch
from launch.runtime_guard import runtime_guard
from main import create_app


def _run(awaitable):
    return asyncio.run(awaitable)


def test_command_driven_gameplay_flow_survives_settlement_and_restart(
    tmp_path: Path, monkeypatch
) -> None:
    """从真实本地命令入口验收一条最小可玩的资源闭环。"""

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
    monkeypatch.setattr(runtime_guard, "lock_file", tmp_path / "server.lock")
    _run(_exercise_flow())


async def _exercise_flow() -> None:
    user_id = "gameplay-flow-user"
    app = create_app()
    async with app.router.lifespan_context(app):
        await LocalEventHandler.run()

        await _command(user_id, "flow-001", "创建人物 林远 男", "人物创建完成")
        await _command(user_id, "flow-002", "人物", "当前状态")
        await _command(user_id, "flow-003", "位置", "所在之地")
        await _command(user_id, "flow-004", "去 丹霞城", "抵达")
        position = await _command(user_id, "flow-005", "位置", "丹霞城")
        assert any(action.data == "交易" for action in position.actions)
        await _command(user_id, "flow-006", "交易", "修行资粮")
        await _command(user_id, "flow-007", "交易 真意", "猎春")
        await _command(user_id, "flow-008", "购买 410089 01", "交易完成")
        await _command(user_id, "flow-009", "人物装配 真意 410089 01 1", "已经装入")

        # 先用一座正式阵藏条目覆盖“布阵”命令入口；炼制本身由地点设施负责，
        # 不在本次闭环测试里伪造炼器材料。
        services = game_app.current_game_services()
        reserve = await services.core.asset.plan_formation_reserve_acquisition(
            user_id, "530001", "01"
        )
        await services.core.database.commit(
            TransactionCommand(
                user_id,
                "flow-010",
                "闭环准备阵藏",
                (reserve.operation,),
                {},
            )
        )
        await _command(user_id, "flow-011", f"布阵 {reserve.stack.state_key}", "已备战")

        await _command(user_id, "flow-012", "探险", "探险启程")
        await _command(user_id, "flow-013", "探险进度", "尚未结束")
        database = services.core.database
        exploration_session = (
            await database.list_for_user(user_id, state_type="exploration_session")
        )[0]
        exploration_end = _stored_time(exploration_session.value, "结束时间")
        await services.features.tanxian.settle(user_id, "flow-014", now=exploration_end)
        await _command(user_id, "flow-015", "探险结算", "探险总结")

        # 探险可能耗尽血气；按玩家实际流程完成闭关恢复后再采集。
        await _command(user_id, "flow-015a", "开始闭关", "入定闭关")
        retreat_session = (
            await database.list_for_user(user_id, state_type="retreat_session")
        )[-1]
        retreat_end = _stored_time(retreat_session.value, "最晚出关时间")
        await services.features.biguan.settle(
            user_id, "flow-015b", now=retreat_end
        )
        await _command(user_id, "flow-015c", "闭关结束", "闭关总结")

        await _command(user_id, "flow-016", "采药", "入山采药")
        await _command(user_id, "flow-017", "采药进度", "采药进度")
        gathering_session = (
            await database.list_for_user(user_id, state_type="gathering_session")
        )[-1]
        gathering_end = _stored_time(gathering_session.value, "最晚结束时间")
        await services.features.caiyao.settle(user_id, "flow-018", now=gathering_end)
        await _command(user_id, "flow-019", "结束采药", "采药总结")

        await _command(user_id, "flow-020", "去 丹泉苑", "抵达")
        await _command(user_id, "flow-021", "炼丹", "可炼丹药")
        await _command(user_id, "flow-022", "纳戒", "物品")

    # 关闭上一个组合根后重新装配服务，验证角色、资产和最近结算不依赖内存。
    restarted_app = create_app()
    async with restarted_app.router.lifespan_context(restarted_app):
        await LocalEventHandler.run()
        await _command(user_id, "flow-023", "人物", "当前状态")
        await _command(user_id, "flow-024", "纳戒", "物品")


async def _command(user_id: str, event_id: str, raw_message: str, expected_text: str):
    result = await dispatch(
        user_id=user_id,
        raw_message=raw_message,
        event_id=event_id,
    )
    assert result.matched, raw_message
    assert len(result.replies) == 1, raw_message
    message = result.replies[0].message
    assert expected_text in message.content, raw_message
    return message


def _stored_time(value: dict, key: str) -> datetime:
    return datetime.fromisoformat(str(value[key]))
