"""位置页的同行道侣那一行必须是可点按钮（甲）。

判据第五条：名字只作显示、句柄一律用编号。这一条把当时的构造式证明搬进仓库：
手工造一页，把一个假道侣分别塞进"同行道侣"栏（我改的那行）与"本地修士"栏（本来就有的成例），
两边都渲染成 QQ 消息，再用同一个正则找可点链接——成例若是空的，说明是方法本身不产链接，
那就不是这一行的问题。留对照行，是为了拒绝"看起来绿了"。
不调真实页，因为那要求人物有地表位置；纯构造更稳，也不需要游戏状态。
"""

from __future__ import annotations

import re
from urllib.parse import unquote

from game.cmd.通用.位置 import reply
from game.core.companion.contracts import LocalCultivator
from game.features.weizhi.contracts import NearbyCultivatorPage
from launch.adapter.qq_protocol.render import render_qq_message

_LINK = re.compile(r'\[[^\]]*\]\(mqqapi://[^)]*')


def _fake() -> LocalCultivator:
    return LocalCultivator(
        companion_id='500001', name='判据样本道侣', gender='女', title='同行',
        description='构造式证明用的假道侣', realm_id='510001', realm_name='筑基',
        level=3, interactable=True,
    )


def _page(**replaced) -> NearbyCultivatorPage:
    page = NearbyCultivatorPage(
        local_cultivators=(), active_companion=None, cultivators=(),
        page=1, page_size=6, has_next=False, truncated=False, visible_count=0,
    )
    page = page if not replaced else page.__class__(**{**page.__dict__, **replaced})
    return page


def _clickable(services, **replaced) -> list[str]:
    feature = services.features.weizhi
    message = reply.nearby_cultivators(feature.copy(), _page(**replaced), ())
    payload = render_qq_message(message)
    content = payload['content'] if isinstance(payload, dict) else str(payload)
    return _LINK.findall(content)


def test_position_companion_row_is_clickable(services) -> None:
    fake = _fake()
    mine = _clickable(services, active_companion=fake)
    control = _clickable(services, local_cultivators=(fake,))

    assert control, '对照行（本地修士）都不可点，说明问题在渲染方法本身，不是这一行'
    assert mine, '同行道侣那一行不可点：名字没有做成按钮'
    assert any('查看 500001' in unquote(hit) for hit in mine), f'按钮没用编号做句柄：{mine}'
