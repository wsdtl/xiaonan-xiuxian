"""装配台的方案、回执与公开错误。"""
from dataclasses import dataclass

Build = dict[str, tuple[dict[str, str] | None, ...]]


class ZhuangpeiFeatureError(ValueError):
    """装配台请求无法完成。"""


class AssemblyCodeError(ZhuangpeiFeatureError):
    """装配码损坏或格式不受支持。"""


@dataclass(frozen=True)
class ZhuangpeiResult:
    code: str
    lines: tuple[str, ...]
    replayed: bool = False

