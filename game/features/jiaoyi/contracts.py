from dataclasses import dataclass

"""交易玩法微服务的稳定公共契约。"""


class TradeFeatureError(RuntimeError):
    """交易玩法无法完成请求。"""


__all__ = ["TradeFeatureError"]


@dataclass(frozen=True)
class TradeAction:
    """交易回执上的动作，字段名与 CommandAction 契约一致。"""

    action_id: str
    label: str
    command: str
    behavior: str
    style: str
