"""切磋结果必须给出**可点的战报地址**，而不是一串裸编号。

第 121 轮记过这个缺口（"切磋打完了没有入口能看那份战报"）：战报页面按
`切磋:<发起者>:<编号>` 取画面，但回执里只印了这串编号，玩家拿不到地址。
"""
from types import SimpleNamespace

from game.cmd.通用.切磋 import reply


class StubFeature:
    """桩：只实现版式用到的两个方法，避免为一条链接拉起整套服务。"""

    def text(self, *keys: str) -> str:
        return "·".join(str(key) for key in keys)

    def winner_label(self, winner: object, challenger: str, target: str) -> str:
        return challenger


def sample() -> SimpleNamespace:
    return SimpleNamespace(
        owner="126698B2CA8E5ACC5479B46A6898F1EA",
        challenge_id="89d7ee65d439df948ebd635b",
        winner="甲",
        user_participants=("甲",),
        target_participants=("乙",),
        actions=12,
        events=473,
    )


def test_report_id_is_the_scheme_the_report_page_reads():
    assert reply.report_id(sample()) == "切磋:126698B2CA8E5ACC5479B46A6898F1EA:89d7ee65d439df948ebd635b"


def test_result_card_carries_a_clickable_battle_url():
    card = str(reply.result(StubFeature(), sample(), "甲", "乙"))
    url = reply.report_url(sample())
    # 地址只要编号：纯 ASCII、无中文、无冒号、不带 owner（战报是非资产数据，按编号分享）。
    assert url.endswith("/battle/89d7ee65d439df948ebd635b"), url
    assert url.isascii() and "126698B2" not in url, url
    assert url in card, card
    # 玩家看得见的这一屏不许泄露内部编号协议（`切磋:<发起者>:<编号>`）。
    assert "切磋:" not in card, card
