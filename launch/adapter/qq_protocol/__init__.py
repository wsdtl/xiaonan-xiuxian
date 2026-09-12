"""QQ 协议层导出。

QQ 有两种等价的入站传输：开放平台 webhook（`launch.adapter.qq_wh`）与网关
WebSocket 长连接（`launch.adapter.qq_ws`）。两者的入站字段、命令匹配、守卫、
事件解析和回复管理器完全一致，差别只在字节到达的方式，所以这些能力只在本包
实现一份。

传输自己的东西留在各自的驱动器包里：webhook 的 HTTP 路由、验签和开放平台
地址验证在 qq_wh，网关 opcode、心跳、重连和关闭码处理在 qq_ws。

本文件刻意保持精简：只转发业务真正需要的公共名称，不再逐个导入内部实现
模块。原因是 `launch/adapter/registry.py` 在**每个命令注册时**都会导入两个
QQ 驱动器，一旦本文件顺手把 manager / render / payload 全链拉进来，任何一个
环节出问题都会让所有游戏命令注册失败、服务起不来。
"""

from .depends import current_qq_event as current_qq_event
from .depends import current_qq_event_id as current_qq_event_id
from .depends import current_qq_event_type as current_qq_event_type
from .depends import current_qq_group_id as current_qq_group_id
from .depends import current_qq_interaction_id as current_qq_interaction_id
from .depends import current_qq_message_id as current_qq_message_id
from .depends import current_qq_payload as current_qq_payload
from .depends import current_qq_send_target as current_qq_send_target
from .depends import current_qq_user_id as current_qq_user_id
from .target import QqSendTarget as QqSendTarget
from .target import qq_group_target as qq_group_target
from .target import qq_private_target as qq_private_target
