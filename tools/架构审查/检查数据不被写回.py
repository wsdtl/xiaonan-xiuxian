"""运行状态不得写回正式 JSON。

判据来自 `data/基础/读取规则.json:62` 的「禁止规则」第三条：
「运行状态不得写回正式 JSON」——而这条规则在 `game/core/data/files.py:503-507` 只被校验了**形状**
（禁止规则必须是非空字符串数组），**内容没有判据在管**。

**判法（跑前跑后对指纹）**：给 `data/` 下全部文件记 sha1 → 建进程内服务（库在 `_输出/临时`）→
把每条注册命令的第一条用法各派发一次 → 再记一次指纹。**只要有一个文件被改动、新增或删除，就是违规。**

2026-10 首次人工验证：1886 个文件，跑完 170 条回执与整套消息判据后改动 0、新增 0、删除 0。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查数据不被写回.py

**退出码：0 = 干净，1 = 有违规。**
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import os
import pathlib
import sys
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SCRATCH = ROOT / "_输出" / "临时"
SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = os.environ["TMP"] = str(SCRATCH)
for _path in (str(ROOT),):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def fingerprints() -> dict[str, str]:
    """data/ 下每个文件的 sha1。"""
    out: dict[str, str] = {}
    for path in DATA.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        out[path.relative_to(ROOT).as_posix()] = hashlib.sha1(path.read_bytes()).hexdigest()
    return out


async def exercise() -> int:
    """建服务、把每条注册命令的第一条用法派发一次，返回派发条数。"""
    from dataclasses import replace

    import game.app as app
    from game.cmd.command import registered_command_routes
    from game.features.chuangjian_renwu.contracts import CreateCharacterRequest
    from launch.adapter.local import dispatch
    from launch.adapter.local.handler import LocalEventHandler

    app.game_config = replace(
        app.game_config,
        database=replace(
            app.game_config.database,
            path=SCRATCH / f"写回判据-{uuid.uuid4().hex[:6]}.db",
        ),
    )
    services = app.build_game_services(data_dir=DATA)
    app._services = services
    LocalEventHandler._build_command_index()
    user_id = "P:写回判据"
    await services.features.chuangjian_renwu.create(
        CreateCharacterRequest(
            user_id=user_id, request_id="写回判据", name="写回甲", gender="男"
        )
    )
    heads = sorted(
        {str(r[0] if isinstance(r, tuple) else r).split()[0] for r in registered_command_routes()}
    )
    from game.cmd.help_registry import help_registry

    sent = 0
    for head in heads:
        entry = help_registry.find(head)
        if entry is None:
            continue
        usages = list(getattr(entry.spec, "usage", ()) or ())
        if not usages:
            continue
        raw = str(usages[0])
        try:
            await dispatch(
                user_id=user_id, raw_message=raw, event_id=f"写回判据-{head}-{sent}"
            )
        except Exception:  # noqa: BLE001 - 失败不掩盖写回检查
            pass
        sent += 1
    return sent


def main() -> int:
    before = fingerprints()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            from loguru import logger

            logger.remove()
        except Exception:  # noqa: BLE001 - 没有 loguru 也要能跑
            pass
        from main import create_app

        create_app()
        sent = asyncio.run(exercise())
    after = fingerprints()
    problems: list[str] = []
    for key, digest in before.items():
        if key not in after:
            problems.append(f"正式 JSON 被删除：{key}")
        elif after[key] != digest:
            problems.append(f"正式 JSON 被改写：{key}")
    for key in after:
        if key not in before:
            problems.append(f"正式 JSON 被新增：{key}")
    if problems:
        for item in problems:
            print(f"   {item}")
        print(f"数据不被写回 {len(problems)} 处有问题")
        return 1
    print(f"数据不被写回 干净（{len(before)} 个文件、派发 {sent} 条命令）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
