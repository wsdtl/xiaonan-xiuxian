"""命令回复共用的轻量展示格式与看板页面共用的 HTTP 头。"""

from __future__ import annotations

from datetime import datetime, timedelta


#: 看板页面统一的基础响应头：不发缓存、按内容嗅探。
#: 原先 11 个 site.py 各写一份逐字相同的内容，收在这里。
PAGE_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}

#: 看板页面统一的内容安全策略：只允许同源脚本与样式。
#: 原先 10 个 site.py 各写一份同一条长串，收在这里。
PAGE_CSP = (
    "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)

#: 舆图 / 百科 / 战报要把图片画在 <canvas> 或内联 data: 图片上，在基础策略上单独放宽 img-src。
PAGE_CSP_WITH_IMAGES = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


def natural_deadline(value: datetime) -> str:
    """用玩家习惯的日期表达展示活动截止时间。"""

    local = value.astimezone()
    today = datetime.now(local.tzinfo).date()
    if local.date() == today:
        prefix = "今日"
    elif local.date() == today + timedelta(days=1):
        prefix = "明日"
    else:
        prefix = f"{local.month}月{local.day}日"
    return f"{prefix} {local:%H:%M}"


def duration(seconds: int) -> str:
    minutes, remainder = divmod(max(0, seconds), 60)
    if not minutes:
        return f"{remainder}秒"
    if not remainder:
        return f"{minutes}分钟"
    return f"{minutes}分{remainder}秒"


def sentence(value: object) -> str:
    text = str(value or "").strip()
    if not text or text[-1] in "。！？!?":
        return text
    return text + "。"


def format_lines(builder: object, text: object) -> str:
    """把一个「多用法」的格式文案铺成多行，并返回首个用法。

    渲染器会把单个字符串里的换行拍平，所以多用法**只能一行一句**地放；
    数据里约定用 ` / ` 分隔不同用法（用法内部仍用 `|` 表示二选一、`[]` 表示可选）。
    """

    parts = [part.strip() for part in str(text or "").split(" / ") if part.strip()]
    if not parts:
        return ""
    line = getattr(builder, "line")
    line(parts[0])
    for part in parts[1:]:
        line("　" + part)
    return parts[0]


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


def error_document(
    title: str,
    icon: str,
    status: str,
    message: object,
    *,
    tone: str = "danger",
    hint: object = "",
    actions: object = (),
) -> object:
    """失败回执的统一形状：一节标题 + 一行状态 + 逐行铺开的说明。

    命令层三十多个 error 回执形状完全一样，只差标题/图标/状态词/说明四件东西；
    收成一处后改一处即改全体（纯去重，行为不变）。`format_lines` 把多用法文案一行一句铺开。
    """

    from message import M

    builder = M.document().section(title, icon=icon)
    builder.line(M.status(status, tone=tone))
    format_lines(builder, message)
    # 尾注：撞墙时补一句「要查写法就发查看帮助」。正文已经是这句就别印两遍（同一句话印两遍就是零信息）。
    if hint and str(hint) not in str(message):
        builder.small(hint)
    if actions:
        from game.cmd.actions import message_actions

        builder.actions(message_actions(actions))
    return builder.build()


__all__ = [
    "PAGE_CSP",
    "PAGE_CSP_WITH_IMAGES",
    "PAGE_HEADERS",
    "duration",
    "error_document",
    "format_lines",
    "natural_deadline",
    "sentence",
    "to_jsonable",
]
