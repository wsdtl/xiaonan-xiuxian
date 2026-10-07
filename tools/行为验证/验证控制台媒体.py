"""验证控制台媒体处理的行为契约。

`ConsoleMediaStore` 负责把消息里的四类图片来源（空值、字符串、Path、字节）统一
物化为页面可引用的 URL，并按内容哈希落盘、按引用清理。这些判定带有文件系统
副作用，出错时不会立刻显形，因此保留为独立验证入口。

用于回归复查：

```powershell
.venv/Scripts/python.exe -X utf8 tools/验证控制台媒体.py
```

退出码 0 表示全部断言通过。
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from io import BytesIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.cmd.后台.天道后台.media import (  # noqa: E402
    EMPTY_OR_TOO_LARGE,
    PLACEHOLDER,
    ConsoleMediaStore,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"payload"
JPG = b"\xff\xd8\xff" + b"payload"
GIF = b"GIF89a" + b"payload"
WEBP = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"payload"
UNKNOWN = b"\x00\x01\x02\x03"


def check(label: str, actual: object, expected: object) -> bool:
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}" + ("" if ok else f" != {expected!r}"))
    return ok


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        store = ConsoleMediaStore(Path(tmp))
        results: list[bool] = []

        # 空与占位符
        results.append(check("None -> 空串", store.materialize(None), ""))
        results.append(check("空字符串 -> 空串", store.materialize("   "), ""))
        results.append(check("占位符原样返回", store.materialize(PLACEHOLDER), PLACEHOLDER))
        # 外部 URL 与站点绝对路径原样返回
        results.append(check("http URL 原样", store.materialize("http://x/y.png"), "http://x/y.png"))
        results.append(check("站点路径原样", store.materialize("/game-console/media/a.png"), "/game-console/media/a.png"))
        # 以 / 开头的字符串按站点绝对路径原样返回（可能是尚未落盘的引用）
        results.append(check("站点绝对路径原样返回", store.materialize("/no/such/file.png"), "/no/such/file.png"))
        # 相对路径且文件不存在 -> 占位符
        results.append(check("相对不存在的路径 -> 占位符", store.materialize("no/such/file.png"), PLACEHOLDER))
        # 已存在的本地文件 -> 走 Path 分支
        local = Path(tmp) / "local.png"
        local.write_bytes(PNG)
        local_result = store.materialize(str(local))
        results.append(check("存在的本地文件被物化", local_result.startswith("/game-console/media/"), True))
        # 不支持的 Python 类型 -> 占位符
        results.append(check("不支持的类型 -> 占位符", store.materialize(12345), PLACEHOLDER))

        # 字节内容：扩展名按签名判定，内容按 sha256 落盘
        for label, payload, suffix in (
            ("PNG 字节", PNG, ".png"),
            ("JPG 字节", JPG, ".jpg"),
            ("GIF 字节", GIF, ".gif"),
            ("WEBP 字节", WEBP, ".webp"),
        ):
            digest = hashlib.sha256(payload).hexdigest()
            expected = f"/game-console/media/{digest}{suffix}"
            results.append(check(label, store.materialize(payload), expected))
            results.append(
                check(f"{label} 已落盘且内容一致", (Path(tmp) / f"{digest}{suffix}").read_bytes(), payload)
            )
        # 未知签名回退
        digest = hashlib.sha256(UNKNOWN).hexdigest()
        fallback = store.materialize(UNKNOWN)
        results.append(check("未知签名走回退后缀", fallback.startswith(f"/game-console/media/{digest}"), True))
        # BytesIO 与 bytes 等价
        results.append(check("BytesIO 与 bytes 同结果", store.materialize(BytesIO(PNG)), store.materialize(PNG)))
        # 超大内容
        huge = b"\x89PNG\r\n\x1a\n" + b"x" * (10 * 1024 * 1024 + 1)
        results.append(check("超 10MiB -> 提示占位符", store.materialize(huge), EMPTY_OR_TOO_LARGE))
        # 空字节
        results.append(check("空字节 -> 提示占位符", store.materialize(b""), EMPTY_OR_TOO_LARGE))
        # 清理只删无引用文件
        keep = store.materialize(PNG)
        store.cleanup({keep})
        remaining = {p.name for p in Path(tmp).iterdir()}
        results.append(check("清理保留被引用文件", Path(keep).name in remaining, True))
        store.cleanup(set())
        results.append(check("清理删除无引用文件", len(list(Path(tmp).iterdir())), 0))

        print()
        if all(results):
            print(f"全部通过：{len(results)} 项断言")
            return 0
        print(f"存在失败：{results.count(False)}/{len(results)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
