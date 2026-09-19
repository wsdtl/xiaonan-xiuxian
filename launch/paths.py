"""项目资源路径工具。

这里放的是项目级资源路径底座，不属于任何业务组件。
业务组件需要读写 static、生成 /static 链接时，都从这里取同一套口径。
"""

from __future__ import annotations

from pathlib import Path

from .config import DEFAULT_PUBLIC_HOST, config

PROJECT_DIR: Path = config.base_dir
STATIC_DIR: Path = PROJECT_DIR / "static"
STATIC_URL_PREFIX = "/static"


def static_path(*parts: object) -> Path:
    """返回 static 目录下的文件路径。"""

    return STATIC_DIR.joinpath(*_path_parts(parts))


def static_url(*parts: object) -> str:
    """返回公开 static URL。

    只负责拼出 `/static/...`，不做公网域名拼接；公网地址由
    `public_url()` 统一补齐协议、域名和端口。
    """

    suffix = "/".join(_url_parts(parts))
    return f"{STATIC_URL_PREFIX}/{suffix}" if suffix else STATIC_URL_PREFIX


def public_url(*parts: object) -> str:
    """为项目公开路径补齐统一域名。

    线上域名未写协议时默认使用 HTTPS；本地未配置域名时使用当前监听端口。
    """

    domain = str(config.project.domain or "").strip().rstrip("/")
    if not domain:
        domain = f"http://{DEFAULT_PUBLIC_HOST}:{config.server.port}"
    elif "://" not in domain:
        domain = f"https://{domain}"
    suffix = "/".join(_url_parts(parts))
    return f"{domain}/{suffix}" if suffix else domain


def _path_parts(parts: tuple[object, ...]) -> list[str]:
    """整理传给 Path.joinpath 的相对路径片段。"""

    result: list[str] = []
    for part in parts:
        text = str(part or "").strip().strip("/\\")
        if text:
            result.extend(piece for piece in text.replace("\\", "/").split("/") if piece)
    return result


def _url_parts(parts: tuple[object, ...]) -> list[str]:
    """整理 URL 路径片段，保留调用方已经处理过的百分号编码。"""

    return _path_parts(parts)
