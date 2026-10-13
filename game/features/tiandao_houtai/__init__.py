"""非资产日志微服务：消息流水（天道后台所用）。

非资产库（database/runtime_log.db）是核心的；库里三个日志各成一个微服务，
本服务管 log_message_flows（维护者观测流水），由二级命令组件「后台/天道后台」使用。
维护者入口经本服务读流水：日志是观测数据，不是游戏规则、不是玩家资产、也不是战斗事实。
"""
from .service import MESSAGE_RETENTION_SECONDS, MessageFlowRow, MessageFlowStore

__all__ = [
    "MESSAGE_RETENTION_SECONDS",
    "MessageFlowRow",
    "MessageFlowStore",
]
