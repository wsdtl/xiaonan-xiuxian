"""命令回复共用的轻量展示格式。"""

from __future__ import annotations

from datetime import datetime, timedelta


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


__all__ = ["duration", "format_lines", "natural_deadline", "sentence"]
