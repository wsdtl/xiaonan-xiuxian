"""天道后台的消息图片落盘与引用清理。

消息里的图片可能是静态目录内的路径、外部 URL、本地文件路径或直接字节内容。
本模块把四种来源统一物化成可供页面引用的 URL，并按需把内容落到控制台媒体目录，
供短期消息记录引用。清理时只删除不再被任何记录引用的文件。

只服务维护者入口，不读取游戏规则或玩家资产。
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from launch.paths import STATIC_DIR, static_url

MEDIA_MAX_BYTES = 10 * 1024 * 1024
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
PLACEHOLDER = "〔图片〕"
EMPTY_OR_TOO_LARGE = "〔图片内容为空或超过 10 MiB〕"


class ConsoleMediaStore:
    """把消息图片物化为页面可引用的 URL，并管理落盘文件。"""

    def __init__(self, media_dir: Path) -> None:
        self.media_dir = Path(media_dir)

    def materialize(self, image: object) -> str:
        """把一条消息里的图片字段转成可供页面引用的字符串。"""

        if image is None:
            return ""
        if isinstance(image, Path):
            return self._from_path(image)
        if isinstance(image, str):
            text = image.strip()
            if not text or text == PLACEHOLDER:
                return text
            if text.startswith(("http://", "https://", "/")):
                return text
            path = Path(text)
            return self._from_path(path) if path.is_file() else PLACEHOLDER
        if isinstance(image, BytesIO):
            return self._from_bytes(image.getvalue())
        if isinstance(image, (bytes, bytearray, memoryview)):
            return self._from_bytes(bytes(image))
        return PLACEHOLDER

    def cleanup(self, referenced: set[str]) -> None:
        """删除媒体目录内不再被任何记录引用的文件。"""

        names = {
            Path(value).name
            for value in referenced
            if value.startswith("/game-console/media/")
        }
        if not self.media_dir.exists():
            return
        for path in self.media_dir.iterdir():
            if path.is_file() and path.name not in names:
                try:
                    path.unlink()
                except OSError:
                    continue

    def _from_path(self, path: Path) -> str:
        try:
            resolved = path.resolve()
            relative = resolved.relative_to(STATIC_DIR.resolve())
            return static_url(*relative.parts)
        except (OSError, ValueError):
            pass
        try:
            return self._from_bytes(path.read_bytes(), suffix=path.suffix)
        except OSError:
            return PLACEHOLDER

    def _from_bytes(self, value: bytes, *, suffix: str = "") -> str:
        if not value or len(value) > MEDIA_MAX_BYTES:
            return EMPTY_OR_TOO_LARGE
        lowered = suffix.lower()
        extension = lowered if lowered in IMAGE_SUFFIXES else _image_suffix(value)
        digest = hashlib.sha256(value).hexdigest()
        filename = f"{digest}{extension}"
        path = self.media_dir / filename
        if not path.exists():
            path.write_bytes(value)
        return f"/game-console/media/{filename}"


def _image_suffix(value: bytes) -> str:
    if value.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if value.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if value.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if value[:4] == b"RIFF" and value[8:12] == b"WEBP":
        return ".webp"
    return ".png"


__all__ = ["ConsoleMediaStore", "MEDIA_MAX_BYTES", "PLACEHOLDER"]
