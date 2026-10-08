"""消息零信息判据：命令返回的正文里不许出现「零信息」内容。

零信息就是「占了地方、什么也没告诉玩家」的东西，四种：

1. **空条目**：战丹 0种 这种点进去只有空清单的条目——点一下是白翻一页；
2. **空栏目**：栏目标题下面什么都没有，或整栏只有一个「无」；
3. **整段等于基准**：一条属性等于它自己的 默认值（= 基准值）就没有信息。属性类的基准
   见 data/战斗/定义/说明.md：加成类必须 100，默认值就是这个属性的基准值；
4. **重复行**：同一条消息里两行一字不差。

语料是**真实派发**出来的，两段：

- 先把人物走到有丹师/器师/阵师的地点，带真实参数发一遍——预览这类深页只有走到地方、
  给对参数才出得来，无参只会得到用法页；**这一段必须先跑**，因为带参派发里有些命令会把
  人物移动或占住行动，跑完再走就走不过去了；
- 再把每条注册命令按几组通用参数各发一遍。

每次运行都用**新的临时库**：固定路径会被上一次运行留下的人物状态污染（派发过一轮之后
血气耗尽，人物走不到丹师那儿，深页永远进不了语料）。

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
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 只看独立的 0：270项 / 160种 里的 0项 不是空条目（前面不能是数字）。
EMPTY_ENTRY = re.compile(r"(?<![0-9])0\s*(种|份|个|页|条|枚|座|项)")
#: 整栏都是这些值，等于这一栏什么都没说。
NEUTRAL = re.compile(r"^(无|空|未装备|未持有|未执掌|0|0[^0-9]*)$")
#: 倍率写法：看起来是加成，×1 其实就是没加成。
MULTIPLIER = re.compile(r"×\s*([0-9.]+)")
#: 「第1/1页」——只有一页还报页码，等于什么都没说。
SINGLE_PAGE = re.compile(r"第\s*(\d+)\s*/\s*(\d+)\s*页")
#: 纯零计数：整行就是一个「标签: 0」。
ZERO_FIELD = re.compile(r"^[^:：]+[:：]\s*0$")
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
TEXT_FORMULA = re.compile(r"\$[^$]*?\\text\{([^}]*)\}[^$]*?\$")
OTHER_FORMULA = re.compile(r"\$[^$]*\$")
#: 通用参数：编号、名称、页码各来一份，让带参分支也进语料。
ARGS = ("", "400001", "100001", "1")
#: 有状态深页：走到地方 + 给对参数才出得来（丹师在云京城、器师在青岚城）。
#: 有状态深页：走到地方 + 给对参数才出得来（丹师在云京城、器师在青岚城）；
#: 地点留空表示不用走，直接发（立宗门这类）。最后落脚的那一处要有阵师——
#: 宽参阶段在那儿发「阵法」，没有阵师就取不到阵法列表那条覆盖。
#: 所以太素坊排在丹霞城之前。
#: 行动类组件各占一个人物：一次行动会占住全部行动（采药中就采不了矿、不能闭关、
#: 不能服丹），所以同一人物跑不了第二个——每个行动用一份干净的人物。
#: 服丹不在这里：它要求人物有损耗（血气或精神不满），新人物造不出那个状态。
#: 宗门生产、宗门战、赠送、切磋、布阵、讨伐、太素坊、归元观、铜雀台、道侣培养同理，
#: 各缺一种造不出来的状态；tools/报告与生成/消息覆盖对账.py 会把它们列出来。
ACTIVITIES = (
    ("采药", ("开始采药", "采药进度")),
    ("采矿", ("开始采矿", "采矿进度")),
    ("闭关", ("开始闭关", "闭关进度")),
)


DEEP = (
    # 洞天这一站必须先跑：立宗门要在原地（山门入口），先跑过几站旅行之后地点就变了，
    # 入山门会报「当前不在本宗山门入口」，洞天里的页面就全都进不了语料。出山门再去各城。
    (
        "",
        (
            "宗门 创建 判据宗",
            "入山门",
            "藏经阁",
            "灵藏",
            "万珍殿",
            "宗门同行",
            "宗门同行 召集",
            "百炼堂",
            "百炼堂 宗门",
            "丹鼎阁",
            "丹鼎阁 宗门",
            # 炉台的预览页必须在洞天里取，出山门之后就只剩错误页了；不带「开炉」的
            # 编号写法就会落到预览页上（带开炉会因为没材料直接报错）。
            "百炼堂 700001",
            "丹鼎阁 100001",
            "演阵台 1",
            "灵脉",
            "灵田",
            "演阵台",
            "演阵台 宗门",
            "纳戒 基础物品 恢复丹",
            # 多分支选择菜单：A|B 参数 不是命令词，宽参阶段扫不到它。
            "查看|借阅功法 400001",
            "出山门",
        ),
    ),
    ("云京城", ("炼丹 清心散", "阵法 530002 黄")),
    ("青岚城", ("炼器 太白惊鸿",)),
    ("太素坊", ("易形",)),
    ("丹霞城", ("查看道侣 谢若棠", "交谈 谢若棠")),

)

_CORPUS: tuple[dict[str, str], dict[str, float]] | None = None
#: 精心挑的深页命令抛异常就记在这儿——那说明页面根本出不来。
_DEEP_FAILURES: list[str] = []
#: 深页命令：它们必须给出真页面，不能是错误页。
_DEEP_COMMANDS: list[str] = []


def _clean(content: str) -> str:
    """剥掉可点链接的 URL 与公式外壳，留下玩家肉眼看到的那层字。"""

    text = LINK.sub(r"\1", content)
    text = TEXT_FORMULA.sub(r"\1", text)
    text = OTHER_FORMULA.sub("", text)
    return text.replace("&nbsp;", " ")


def _lines(body: str) -> list[str]:
    return [line.lstrip("> ").strip() for line in body.splitlines() if line.strip()]


def _depth_lines(body: str) -> list[tuple[int, str]]:
    """每行的层数与文字。层数就是开头的 > 个数——别用 lstrip 数，它一次吃两个字符。"""

    rows: list[tuple[int, str]] = []
    for raw in body.splitlines():
        if not raw.strip():
            continue
        depth = 0
        for char in raw:
            if char == ">":
                depth += 1
            elif char != " ":
                break
        rows.append((depth, raw.lstrip("> ").strip()))
    return rows


def _sections(body: str) -> list[tuple[str, list[str]]]:
    """把正文切成「栏目标题 -> 它的内容行」。

    渲染器在同一层上放三种东西：**栏目标题**（只有图标加名字）、**自带内容的行**（同一行
    就有冒号，例如「伤势: 无」）和空行分隔符。只有第一种才是栏目；认错了会把自带内容的行
    当成空栏目。
    """

    sections: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for depth, item in _depth_lines(body):
        if not item:
            continue
        if depth == 1:
            current = None if (":" in item or "：" in item) else []
            if current is not None:
                sections.append((item, current))
        elif depth >= 2 and current is not None:
            current.append(item)
    return sections


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

    from game.core.asset import InventoryAdjustment
    from game.core.database import TransactionCommand
    from game.features.chuangjian_renwu.contracts import CreateCharacterRequest
    from game.features.xinglu.contracts import TravelRequest
    from launch.adapter.local import dispatch
    from launch.adapter.local.handler import LocalEventHandler

    scratch = ROOT / "_输出" / "临时"
    scratch.mkdir(parents=True, exist_ok=True)
    database = scratch / ("消息判据-" + uuid.uuid4().hex[:8] + ".db")
    app.game_config = replace(
        app.game_config,
        database=replace(app.game_config.database, path=database),
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
    deep_failures: list[str] = []

    async def send(text: str, *, user: str = "", strict: bool = False) -> None:
        try:
            result = await dispatch(
                user_id=user or user_id, raw_message=text, event_id="判据-" + text
            )
        except Exception as exc:  # noqa: BLE001 - 参数不合适的命令本来就会报错
            if strict:
                deep_failures.append(text + " 派发时抛了 " + type(exc).__name__ + "：" + str(exc)[:60])
            return
        if result.replies and text not in pages:
            # 先到先得：宽参阶段会把「命令 + 空参数」拼成同一条命令，覆盖掉深页阶段
            # 在正确状态下取到的页面——那一覆盖正是让洞天覆盖悄悄失效的原因。
            pages[text] = _clean(getattr(result.replies[0].message, "content", ""))

    async def run() -> None:
        await services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=user_id, request_id="消息判据", name="判据甲", gender="男"
            )
        )
        # 深页那一套要干净的人物走到指定地点；宽参那一套要留在初始状态——
        # 深页会把人物带进洞天或各城，之后采药/闭关这类本地命令就全报错了，
        # 早先 42 个组件里有 15 个因此一条真页面都没有。两个人各管一套。
        # 切磋要另一个人物，布阵要阵藏里先有一座阵法——这两件事不是派发命令能造的，
        # 所以在这里直接建人物、直接授予，再把命令发出去。
        partner = "P:判据乙"
        await services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=partner, request_id="消息判据-乙", name="判据乙", gender="女"
            )
        )
        clash_name = "判据乙"
        # 易形要纳戒里先有两仪易形丹（160004）；它不是派发命令能造的。
        pill_plan = await services.core.asset.plan_inventory_changes(
            user_id, (InventoryAdjustment("160004", "01", 1),)
        )
        await services.core.database.commit(
            TransactionCommand(
                user_id,
                "判据易形丹",
                "消息判据",
                tuple(pill_plan.operations),
                {"物品": "160004"},
            )
        )
        formation_plan = await services.core.asset.plan_formation_reserve_acquisition(
            user_id, "530002", "01"
        )
        await services.core.database.commit(
            TransactionCommand(
                user_id,
                "判据阵藏",
                "消息判据",
                (formation_plan.operation,),
                {"阵法": "530002"},
            )
        )
        for command in ("布阵 诛仙剑阵 黄品",):
            _DEEP_COMMANDS.append(command)
            await send(command, strict=True)
        for command in ("切磋 " + clash_name,):
            _DEEP_COMMANDS.append(command)
            await send(command, strict=True)

        for place, commands in DEEP:
            if place:
                try:
                    await services.features.xinglu.travel(
                        TravelRequest(
                            user_id=user_id, request_id="判据-" + place, destination=place
                        )
                    )
                except Exception:  # noqa: BLE001 - 走不到就跳过这一站
                    continue
            for command in commands:
                _DEEP_COMMANDS.append(command)
                await send(command, strict=True)
        words = sorted(
            set(LocalEventHandler.command_rules) | set(LocalEventHandler.fullmatch_rules)
        )
        # 讨伐一开就占住行动，跟宽参阶段共用人物会把探险那几条挤成错误页；
        # 给它一份独立人物，和行动类同样的做法。
        raid_user = "P:判据讨伐"
        await services.features.chuangjian_renwu.create(
            CreateCharacterRequest(
                user_id=raid_user, request_id="消息判据-讨伐", name="判据讨", gender="男"
            )
        )
        try:
            await services.features.xinglu.travel(
                TravelRequest(
                    user_id=raid_user, request_id="判据-镇北军镇", destination="镇北军镇"
                )
            )
        except Exception:  # noqa: BLE001 - 走不到就不跑这一段
            pass
        else:
            for command in ("开始讨伐", "讨伐战况"):
                _DEEP_COMMANDS.append(command)
                await send(command, user=raid_user, strict=True)
        for label, commands in ACTIVITIES:
            activity_user = "P:判据行动" + label
            await services.features.chuangjian_renwu.create(
                CreateCharacterRequest(
                    user_id=activity_user,
                    request_id="消息判据-" + label,
                    name="判据" + label[:1],
                    gender="男",
                )
            )
            for command in commands:
                _DEEP_COMMANDS.append(command)
                await send(command, user=activity_user, strict=True)
        for word in words:
            for arg in ARGS:
                await send((word + " " + arg).strip())

    asyncio.run(run())
    baselines = dict(services.core.character.attribute_baselines())
    services.core.database.close()
    for leftover in scratch.glob(database.name + "*"):
        leftover.unlink(missing_ok=True)
    _DEEP_FAILURES.extend(deep_failures)
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


def check_no_empty_sections() -> list[str]:
    """栏目要么别开，要么给出内容：标题下什么都没有、或整栏只有一个「无」，都是白占地方。"""

    problems: list[str] = []
    pages, _ = _corpus()
    for word, body in pages.items():
        for title, content in _sections(body):
            if not content:
                problems.append(word + " 的正文里有空栏目：" + title[:40])
            elif all(NEUTRAL.match(item) for item in content):
                problems.append(word + " 的栏目整栏都是中性值：" + title[:40])
    return problems


def check_no_baseline_padding() -> list[str]:
    """整段属性都等于基准，就等于整段什么都没说。"""

    problems: list[str] = []
    pages, baselines = _corpus()
    for word, body in pages.items():
        for title, content in _sections(body):
            pairs: list[tuple[str, str]] = []
            for line in content:
                for part in line.split('|'):
                    label, separator, value = part.partition(":")
                    if separator and label.strip() in baselines:
                        pairs.append((label.strip(), value.strip()))
            if pairs and all(_number(value) == baselines[label] for label, value in pairs):
                names = "、".join(label for label, _ in pairs[:4])
                problems.append(word + " 的栏目整段属性等于基准：" + title[:30] + "（" + names + "…）")
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


def check_no_neutral_multipliers() -> list[str]:
    """全是 ×1 的倍率行等于「没有加成」，别占地方。

    只看带冒号的「标签: 值」行——兽宝 × 1 那种是数量，有用的。
    """

    problems: list[str] = []
    pages, _ = _corpus()
    for word, body in pages.items():
        for line in _lines(body):
            if ":" not in line and "：" not in line:
                continue
            found = MULTIPLIER.findall(line)
            if found and all(float(value) == 1 for value in found):
                problems.append(word + " 的正文里有中性倍率行：" + line[:60])
    return problems


def check_deep_pages_work() -> list[str]:
    """深页命令是精心挑的，跑了就该出页面；抛异常说明这条出口是坏的。"""

    _corpus()
    return [item + "（深页出口坏了）" for item in _DEEP_FAILURES]


def check_no_single_page_marker() -> list[str]:
    """只有一页就不该报「第1/1页」——那是零信息。"""

    problems: list[str] = []
    pages, _ = _corpus()
    for word, body in pages.items():
        for line in _lines(body):
            for current, total in SINGLE_PAGE.findall(line):
                if current == total == "1":
                    problems.append(word + " 的正文里给单页报了页码：" + line[:40])
    return problems


def check_no_zero_count_with_empty_note() -> list[str]:
    """同一栏目里既印「计数: 0」又印「空」——同一件事说两遍。"""

    problems: list[str] = []
    pages, _ = _corpus()
    for word, body in pages.items():
        for title, content in _sections(body):
            zero = [item for item in content if ZERO_FIELD.match(item)]
            if zero and any(item.startswith("空") for item in content):
                problems.append(word + " 的栏目同时印了零计数与空陈述：" + title[:30] + "（" + zero[0][:20] + "）")
    return problems


def check_deep_pages_are_real() -> list[str]:
    """深页命令必须给出真页面：拿到错误页说明这一站的覆盖是假的。"""

    pages, _ = _corpus()
    problems: list[str] = []
    for command in _DEEP_COMMANDS:
        body = pages.get(command)
        if body is None:
            problems.append(command + " 没有页面（深页覆盖为假）")
            continue
        for marker in ("失败", "受阻", "尚未加入"):
            if marker in body:
                problems.append(command + " 拿到的是错误页：" + body.splitlines()[-1][:50])
                break
    return problems


def check_badge_not_restated() -> list[str]:
    """状态徽章后面又跟一句复述它的话，就是同一件事印两遍。

    只看「第一个词 + 空格 + 其余」这种行（第一个词不含冒号），并且第一个词要真的
    出现在其余文字里——例如「未同行 如今并未同行」。像「可结束 现在可以结束采药」
    这种同义但不同字的复述抓不住，那一类只能靠人看。
    """

    problems: list[str] = []
    pages, _ = _corpus()
    for word, body in pages.items():
        for line in _lines(body):
            head, separator, rest = line.partition(" ")
            if not separator or ":" in head or "：" in head or len(head) < 2:
                continue
            if head in rest:
                problems.append(word + " 的正文里徽章被复述：" + line[:50])
    return problems


CHECKS = (
    ("没有空条目", check_no_empty_entries),
    ("没有空栏目", check_no_empty_sections),
    ("没有整段基准", check_no_baseline_padding),
    ("没有重复行", check_no_duplicate_lines),
    ("没有中性倍率", check_no_neutral_multipliers),
    ("深页能出页面", check_deep_pages_work),
    ("深页不是错误页", check_deep_pages_are_real),
    ("单页不报页码", check_no_single_page_marker),
    ("零计数不配空陈述", check_no_zero_count_with_empty_note),
    ("徽章不被复述", check_badge_not_restated),
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
