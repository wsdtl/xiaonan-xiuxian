"""品级露出判据：展示实例的出口必须给出该实例的品级。

品级是**实例级**事实：data/基础/定义/编号.json 明写「编号不承载品级」，功法实体只有
编号/名称/说明/属性构成/权重/能力，品级在取得时才带上、住在道藏与资粮实例上。所以
实体级的详情如果不说品级，玩家就看不到「我这份」和别人的差别。

三组检查：

1. 查看页必须给出品级行；
2. 装配台详情必须给出品级与能力倍率，并且**卡面正文不随品级变化**——守
   data/基础/定义/说明.md 的缩放禁令：能力倍率只作用于协议允许缩放的数值，
   不得遍历所有数字无差别改写卡面；
3. 器律按器阶划分，传品级必须被拒。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查品级露出.py

**退出码：0 = 干净，1 = 有缺口。**
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GRADE_WORD = "品级："
SAMPLES = ("400001", "100001", "200001")


_SERVICES: object | None = None


def _services():
    """全程只建一次：三组检查共用同一份服务，建一次约 2 秒，建三次就是白烧。"""

    global _SERVICES
    if _SERVICES is not None:
        return _SERVICES
    import game.app as app
    from dataclasses import replace

    scratch = ROOT / "_输出" / "临时"
    scratch.mkdir(parents=True, exist_ok=True)
    app.game_config = replace(
        app.game_config,
        database=replace(app.game_config.database, path=scratch / "品级判据.db"),
    )
    # 建服务会打一屏启动日志（loguru 走 stderr）；判据只要结论，不把噪声混进总账。
    from loguru import logger

    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        logger.remove()
        _SERVICES = app.build_game_services(data_dir=ROOT / "data")
    return _SERVICES


async def check_view_shows_grade() -> list[str]:
    """查看页对每个体裁都要给出品级行。"""

    from launch.adapter.qq_protocol.render import render_qq_message
    from game.cmd.通用.查看 import reply as view_reply

    services = _services()
    problems: list[str] = []
    try:
        for entity_id in SAMPLES:
            result = await services.features.chakan_wupin.inspect(entity_id, "")
            payload = render_qq_message(view_reply.inspection(result))
            content = payload["content"] if isinstance(payload, dict) else str(payload)
            if GRADE_WORD not in content:
                problems.append("查看 " + entity_id + " 的页面里没有品级行")
    finally:
        pass
    return problems


async def check_assembly_detail_shows_grade() -> list[str]:
    """装配台详情给出品级与能力倍率，且卡面正文逐字不随品级变化。"""

    services = _services()
    problems: list[str] = []
    try:
        feature = services.features.zhuangpei
        low = feature.detail("功法", "400001", "01")
        high = feature.detail("功法", "400001", "05")
        for label, value in (("黄品", low), ("圣品", high)):
            head = value["lines"][0] if value["lines"] else ""
            if GRADE_WORD not in head:
                problems.append("装配台详情缺品级行（" + label + "）")
            if "能力 ×" not in head:
                problems.append("装配台详情的品级行没给出能力倍率（" + label + "）")
        if low["lines"][1:] != high["lines"][1:]:
            problems.append("卡面正文随品级变了——缩放禁令要求逐个数字逐字不变")
        if low["lines"][0] == high["lines"][0]:
            problems.append("不同品级的详情行一模一样——品级没生效")
    finally:
        services.core.database.close()
    return problems


async def check_law_rejects_grade() -> list[str]:
    """器律按器阶划分，带品级必须被拒。"""

    services = _services()
    problems: list[str] = []
    try:
        try:
            services.features.zhuangpei.detail("器律", "700001", "01")
        except Exception as exc:  # noqa: BLE001 - 拒绝就是期望行为
            if "器阶" not in str(exc):
                problems.append("器律拒绝品级的原因不清楚：" + str(exc))
        else:
            problems.append("器律带品级竟然通过了")
    finally:
        services.core.database.close()
    return problems


CHECKS = (
    ("查看页露出品级", check_view_shows_grade),
    ("装配台详情露出品级", check_assembly_detail_shows_grade),
    ("器律拒绝品级", check_law_rejects_grade),
)


def main() -> int:
    problems: list[str] = []
    for name, check in CHECKS:
        found = asyncio.run(check())
        print("  [" + name + "] " + ("干净" if not found else str(len(found)) + " 处"))
        for item in found[:20]:
            print("    " + item)
        problems.extend(found)
    if _SERVICES is not None:
        _SERVICES.core.database.close()
    if problems:
        print("品级露出 " + str(len(problems)) + " 处有问题")
        return 1
    print("品级露出判据通过：" + str(len(CHECKS)) + " 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
