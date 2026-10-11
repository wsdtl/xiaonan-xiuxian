"""网页拼给玩家的命令，必须真能发得出去。

这条判据来自一个真缺陷：万珍殿网页对阵法拼的是「捐入万珍殿 阵法 530002」（只有阵法编号），
而后端要的是阵藏状态键「530002:01:无灵宝」——玩家照抄必然收到「阵藏中没有该阵法」。
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import pathlib
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _static_problems() -> list[str]:
    problems: list[str] = []
    script = ROOT / 'static' / 'wanzhen' / 'app.js'
    text = script.read_text(encoding='utf-8')
    for number, line in enumerate(text.splitlines(), start=1):
        if '捐入万珍殿 阵法' not in line:
            continue
        # 阵法只报名字：状态键（阵法编号:品级:灵宝编号）与纯阵法编号都是代码内部的东西，玩家不该见。
        if 'item.key' in line or 'item.id' in line:
            problems.append(
                'static/wanzhen/app.js:%d 阵法命令用了条目键/编号，玩家看到的是机器键' % number
            )
        elif 'item.name' not in line:
            problems.append(
                'static/wanzhen/app.js:%d 阵法命令既没用阵法名，也没报出条目键/编号' % number
            )
    return problems

async def _runtime_problems() -> list[str]:
    import game.app as app
    from dataclasses import replace
    from game.features.chuangjian_renwu.contracts import CreateCharacterRequest
    from game.features.xinglu.contracts import TravelRequest
    from game.core.asset import InventoryAdjustment
    from game.core.database import TransactionCommand
    from game.cmd.专属.万珍殿.site import _entries
    from launch.adapter.local import dispatch
    from launch.adapter.local.handler import LocalEventHandler

    problems: list[str] = []
    scratch = ROOT / '_输出' / '临时'
    scratch.mkdir(parents=True, exist_ok=True)
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from loguru import logger
        logger.remove()
        app.game_config = replace(
            app.game_config,
            database=replace(
                app.game_config.database,
                path=scratch / ('网页命令-' + uuid.uuid4().hex[:6] + '.db'),
            ),
        )
        services = app.build_game_services(data_dir=ROOT / 'data')
    app._services = services
    LocalEventHandler._build_command_index()
    user_id = 'P:网页命令判据'
    await services.features.chuangjian_renwu.create(
        CreateCharacterRequest(user_id=user_id, request_id='网页判据', name='网判', gender='男')
    )
    await services.features.xinglu.travel(
        TravelRequest(user_id=user_id, request_id='网页判据-园', destination='宗门园区')
    )
    await dispatch(user_id=user_id, raw_message='宗门 创建 网判宗', event_id='网页判据-宗')
    stones = await services.core.asset.plan_inventory_changes(
        user_id, (InventoryAdjustment('100001', '01', 9000),)
    )
    await services.core.database.commit(
        TransactionCommand(user_id, '网页判据-灵石', '网页判据', tuple(stones.operations), {'物品': '100001'})
    )
    await dispatch(user_id=user_id, raw_message='入山门', event_id='网页判据-入')
    reserve = await services.core.asset.plan_formation_reserve_acquisition(user_id, '530002', '01')
    await services.core.database.commit(
        TransactionCommand(user_id, '网页判据-阵藏', '网页判据', (reserve.operation,), {'阵法': '530002'})
    )
    rows = await _entries(services, user_id)
    formations = [row for row in rows if '阵法' in str(row['subcategory'])]
    if not formations:
        problems.append('网页条目里没有阵法，判据本身失效')
        return problems
    for row in formations:
        if not str(row.get('name') or ''):
            problems.append('网页条目 %s 没带阵法名，页面拼不出命令' % row.get('id'))
    first = formations[0]
    tail = '[' + str(first['treasure_name']) + ']' if first.get('treasure_name') else ''
    command = '捐入万珍殿 阵法 ' + str(first['name']) + tail
    result = await dispatch(user_id=user_id, raw_message=command, event_id='网页判据-捐')
    text = str(getattr(result.replies[0].message, 'content', '')) if result.replies else ''
    if '存入' not in text:
        problems.append('照网页拼出的命令发不出去：%s' % command)
    return problems


def main() -> int:
    problems = _static_problems()
    problems.extend(asyncio.run(_runtime_problems()))
    if problems:
        print('网页命令 ' + str(len(problems)) + ' 处')
        for item in problems:
            print('  ' + item)
        return 1
    print('网页命令审查通过：2 项检查')
    return 0


if __name__ == '__main__':
    sys.exit(main())