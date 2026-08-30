"""通过 QQ 驱动器发送 Markdown 与公式混合预览。"""

from launch.adapter.qq import QqEventHandler

from .reply import build_preview, list_cases


@QqEventHandler.command("公式预览")
async def formula_preview(*, message: str, manager, **_) -> None:
    raw = str(message or "").strip()
    if not raw:
        await manager.send(list_cases())
        return
    if not raw.isdecimal():
        await manager.send(list_cases(error="格式：公式预览 [编号]"))
        return
    await manager.send(build_preview(int(raw)))
