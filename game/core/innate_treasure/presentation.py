"""先天灵宝激活结果的结算投影。

激活结果由本服务产生，而把它转成结算载荷的动作原先在六个服务里各抄一份
（炼丹、炼器、阵法、采集、闭关、服丹），六份逐字节相同、各自只有一个调用点。
载荷字段由**定义这个类型的包**给出：`InnateTreasureActivation` 的字段一变，
六处不会各自漂移。
"""

from __future__ import annotations

from .contracts import InnateTreasureActivation


def activation_payload(
    activation: InnateTreasureActivation | None,
) -> dict[str, str] | None:
    """把激活结果转成结算载荷；本回合没有激活时返回 `None`。"""

    if activation is None:
        return None
    return {
        "编号": activation.treasure_id,
        "名称": activation.name,
        "权柄": activation.authority,
        "结果": activation.summary,
    }


__all__ = ["activation_payload"]
