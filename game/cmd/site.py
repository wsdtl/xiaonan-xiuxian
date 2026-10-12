"""命令层共用的只读看板 HTTP 契约。

只读看板（灵宝谱 / 货架 / 归元观 / 铜雀台 / 灵田 / 演阵台 / 补天 / 装配台 / 舆图 /
百科 / 战报）由各自的 site.py 下发 HTML 与 JSON，响应头与失败回执原先每个文件
各写一份、内容逐字相同。收在这里，与 presentation.py（消息展示格式）分开：

- presentation.py 只管**消息**（builder / M 那套），任何 reply.py 都会导入它；
- 本模块只管**HTTP**（响应头、JSON 失败回执），只有那些 site.py 会导入。

分开的好处是 fastapi 不会被拖进消息回复的导入链。各页**自己的**内容安全策略仍写在
自己的 site.py 里（下发 HTML 的模块自己声明策略，检查静态资源.py 按这一条判）。
"""

from __future__ import annotations

#: 只读看板统一的基础响应头：不发缓存、按内容嗅探。
PAGE_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}

#: 基础内容安全策略：只允许同源脚本与样式。
PAGE_CSP = (
    "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)

#: 舆图 / 百科 / 战报要把图片画在 canvas 或内联 data: 图片上，在基础策略上单独放宽 img-src。
PAGE_CSP_WITH_IMAGES = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


def page_headers(*, csp: str = PAGE_CSP) -> dict[str, str]:
    """看板页面的响应头：共用基础头 + 本页的 CSP 与来源限制。"""

    return {
        **PAGE_HEADERS,
        "Content-Security-Policy": csp,
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "SAMEORIGIN",
    }


def failure(message: str, status: int = 400) -> object:
    """只读看板共用的失败回执：一条错误正文，状态码默认 400。"""

    from fastapi.responses import JSONResponse

    return JSONResponse({"error": message}, status_code=status, headers=PAGE_HEADERS)


def to_jsonable(value: object) -> object:
    """把核心返回的结构（含 dataclass）转成可 JSON 序列化的普通对象。

    四个只读看板（灵宝谱 / 货架 / 归元观 / 铜雀台）原先各抄一份逐字相同的实现，
    收在这里；行为不变——标量原样、映射转字典、序列转列表、dataclass 按字段展开，
    认不出的落成字符串。
    """

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "items"):
        return {str(key): to_jsonable(raw) for key, raw in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    fields = getattr(value, "__dataclass_fields__", None)
    if fields:
        return {name: to_jsonable(getattr(value, name)) for name in fields}
    return str(value)


__all__ = [
    "PAGE_CSP",
    "PAGE_CSP_WITH_IMAGES",
    "PAGE_HEADERS",
    "failure",
    "page_headers",
    "to_jsonable",
]
