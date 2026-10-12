"""QQ 协议层共用的标识缩短。

开放平台的长 ID（file_uuid、msg_id、user_id、session_id…）直接进日志会把一行撑得很长。
这里只做一件事：**保留首尾、中间省略**，既方便排查又能读。三处调用（OpenAPI 客户端、
回复管理器、派发运行时）原先各抄一份逐字相同的实现，统一到这里；`processor` 继续
从包顶层再导出 `short_id`，外部引用不变。
"""

from __future__ import annotations


def short_id(value: object, head: int = 8, tail: int = 6) -> str:
    """缩短开放平台长 ID，保留首尾方便排查。"""

    text = str(value or "").strip()
    if not text:
        return "-"
    if len(text) <= head + tail + 3:
        return text
    return f"{text[:head]}...{text[-tail:]}"


__all__ = ["short_id"]
