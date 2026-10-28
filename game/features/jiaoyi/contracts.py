from dataclasses import dataclass

from game.core.trade import TradeOverview, TradePage

"""交易玩法微服务的稳定公共契约。"""


class TradeFeatureError(RuntimeError):
    """交易玩法无法完成请求。"""




@dataclass(frozen=True)
class TradeAction:
    """交易回执上的动作，字段名与 CommandAction 契约一致。"""

    action_id: str
    label: str
    command: str
    behavior: str
    style: str


@dataclass(frozen=True)
class TradeQueryEntry:
    """一次交易查询根命令的结果；分支与页码由玩法判定。"""

    kind: str
    overview: TradeOverview | None = None
    page: TradePage | None = None


__all__ = ["TradeAction", "TradeFeatureError", "TradeQueryEntry"]
