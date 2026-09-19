"""通信框架的协议中立公共 API。

业务组件从这里注册命令、读取公共上下文、发送回复或主动推送。具体 QQ 字段
必须从 launch.adapter.qq_protocol.depends 显式声明，不能扩散到这个出口。

本文件只做公共名称转发，不放实现逻辑。业务代码从这里导入；驱动器内部则
直接使用自己的子模块。名称按来源模块排列，阅读时可以快速找到需要的入口。
"""

from .base_handler import BaseAdapter as BaseAdapter
from .base_handler import BaseMessageHandler as BaseMessageHandler
from .command_guard import CommandGuardContext as CommandGuardContext
from .command_guard import CommandGuardDecision as CommandGuardDecision
from .command_guard import register_command_guard as register_command_guard
from .command_guard import registered_command_guards as registered_command_guards
from .command_guard import run_command_guards as run_command_guards
from .command_guard import unregister_command_guard as unregister_command_guard
from .context import MENTION_DEFAULT as MENTION_DEFAULT
from .context import MENTION_NONE as MENTION_NONE
from .context import MENTION_SENDER as MENTION_SENDER
from .context import MessageContext as MessageContext
from .context import ReplyTarget as ReplyTarget
from .context import SendOptions as SendOptions
from .context import SendRequest as SendRequest
from .context import current_message_context as current_message_context
from .context import current_reply_target as current_reply_target
from .depends import Depends as Depends
from .registry import AdapterHttpMount as AdapterHttpMount
from .registry import AdapterReplyManager as AdapterReplyManager
from .registry import AdapterSpec as AdapterSpec
from .registry import MessageHandler as MessageHandler
from .registry import available_adapter_specs as available_adapter_specs
from .registry import enabled_adapter_names as enabled_adapter_names
from .registry import enabled_adapter_specs as enabled_adapter_specs
from .registry import manager as manager


async def dispatch_local_message(*args, **kwargs):
    """通过公开适配器入口向本地驱动器分发消息。"""

    from .local import dispatch

    return await dispatch(*args, **kwargs)
