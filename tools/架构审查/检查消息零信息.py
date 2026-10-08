"""消息零信息判据：命令返回的正文里不许出现「零信息」内容。

零信息就是「占了地方、什么也没告诉玩家」的东西，三种：

1. **空条目**：战丹 0种 这种点进去只有空清单的条目——点一下是白翻一页；
2. **整段等于基准**：一条属性等于它自己的 默认值（= 基准值）就没有信息。属性类的基准
   见 data/战斗/定义/说明.md：加成类必须 100，默认值就是这个属性的基准值；
3. **重复行**：同一条消息里两行一字不差。

语料是**真实派发**出来的：建一份临时服务、建一个人物，把注册的每条命令都发一遍，
取其第一条回复的正文。这样量到的是玩家真看到的东西，不是静态猜的。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查消息零信息.py

**退出码：0 = 干净，1 = 有零信息内容。**
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 0种 / 0份 / 0个 / 0页 这类「空条目」。
EMPTY_ENTRY = re.compile(r"0\s*(种|份|个|页|条|枚|座|项)")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
TEXT_FORMULA = re.compile(r"\$[^$]*?\\text\{([^}]*)\}[^$]*?\$")
OTHER_FORMULA = re.compile(r"\$[^$]*\$")

_CORPUS: tuple[dict[str, str], dict[str, float]] | None = None


def _clean(content: str) -> str:
    """剥掉可点链接的 URL 与公式外壳，留下玩家肉眼看到的那层字。"""

    text = LINK.sub(r"\1", content)
    text = TEXT_FORMULA.sub(r"\1", text)
    text = OTHER_FORMULA.sub("", text)
    return text.replace("&nbsp;", " ")


def _lines(body: str) -> list[str]:
    return [line.lstrip("> ").strip() for line in body.splitlines() if line.strip()]


def _number(value: str) -> float:
    digits = re.sub(r"[^0-9.-]", "", value)
    try:
        return float(digits)
    except ValueError:
        return float("nan")


def _corpus() -> tuple[dict[str, str], dict[str, float]]:
    """真实派发一遍全部命令，全程只建一次。"""

    global _CORPUS
    if _CORPUS is not None:
        return _CORPUS
    import game.app as app
    import game.cmd  # noqa: F401 - 注册全部命令组件
    from dataclasses import replace

    from game.features.chuangjian_renwu.contracts import CreateCharacterRequest
    from launch.adapter.local import dispatch
    from launch.adapter.local.handler import LocalEventHandler

    scratch = ROOT / "_输出" / "临时"
    scratch.mkdir(parents=True, exist_ok=True)
    app.game_config = replace(
        app.game_config,
        database=replace(app.game_config.database, path=scratch / "消息判据.db"),
    )
    # 启动日志走 loguru，先摘掉，别把一屏噪声混进总账。
    from loguru import logger

    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        logger.remove()
        services = app.build_game_services(data_dir=ROOT / "data")
    app._services = services
    LocalEventHandler._build_command_index()
    user_id = "P:消息判据"
    pages: dict[str, str] = {}

    async def run() -> None:
        await services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id, request_id="消息判据", name="判据甲", gender="男"
            )
        )
        words = sorted(
            set(LocalEventHandler.command_rules) | set(LocalEventHandler.fullmatch_rules)
        )
        for word in words:
            try:
                result = await dispatch(
                    user_id=user_id, raw_message=word, event_id="消息判据-" + word
                )
            except Exception:  # noqa: BLE001 - 最少参数派发本来就会有些命令报错
                continue
            if result.replies:
                content = getattr(result.replies[0].message, "content", "")
                pages[word] = _clean(content)

    asyncio.run(run())
    baselines = dict(services.core.character.attribute_baselines())
    services.core.database.close()
    _CORPUS = (pages, baselines)
    return _CORPUS


def check_no_empty_entries() -> list[str]:
    """点进去只有空清单的条目一律不许出现。"""

    problems: list[str] = []
    pages, _ = _corpus()
    for word, body in pages.items():
        for line in _lines(body):
            if EMPTY_ENTRY.search(line):
                problems.append(word + " 的正文里有空条目：" + line[:60])
    return problems


def check_no_baseline_padding() -> list[str]:
    """整段属性都等于基准，就等于整段什么都没说。"""

    problems: list[str] = []
    pages, baselines = _corpus()
    for word, body in pages.items():
        pairs: list[tuple[str, str]] = []
        for line in _lines(body):
            for part in line.split("|"):
                label, separator, value = part.partition(":")
                if separator and label.strip() in baselines:
                    pairs.append((label.strip(), value.strip()))
        if pairs and all(_number(value) == baselines[label] for label, value in pairs):
            names = "、".join(label for label, _ in pairs[:4])
            problems.append(word + " 的正文整段属性等于基准：" + names + "…")
    return problems


def check_no_duplicate_lines() -> list[str]:
    """同一条消息里两行一字不差，就是同一件事印了两遍。"""

    problems: list[str] = []
    pages, _ = _corpus()
    for word, body in pages.items():
        seen: set[str] = set()
        for line in _lines(body):
            if len(line) < 10:
                continue
            if line in seen:
                problems.append(word + " 的正文里有重复行：" + line[:60])
            seen.add(line)
    return problems


CHECKS = (
    ("没有空条目", check_no_empty_entries),
    ("没有整段基准", check_no_baseline_padding),
    ("没有重复行", check_no_duplicate_lines),
)


def main() -> int:
    problems: list[str] = []
    for name, check in CHECKS:
        found = check()
        print("  [" + name + "] " + ("干净" if not found else str(len(found)) + " 处"))
        for item in found[:20]:
            print("    " + item)
        problems.extend(found)
    if problems:
        print("消息零信息 " + str(len(problems)) + " 处")
        return 1
    print("消息零信息判据通过：" + str(len(CHECKS)) + " 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
