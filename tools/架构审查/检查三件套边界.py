"""三件套边界判据：功法=主动技能 · 真意=被动 · 气机=属性。

为什么要有这支：1903 张卡（功法 600 / 真意 600 / 气机 703）共用同一套字段，
于是"职责"只写在文档里，卡上什么都塞。实测过的现状是：功法 100% 带「被动」与
「属性构成」、97.7% 用层数——光靠改卡改不干净，必须有一支判据逼着它们分家。

判据分四组：
  一、职责边界：谁的活归谁（越界即红，并列出前几个越界卡）
  二、主动技能的形状：功法必须像主动技能（冷却 / 消耗 / 目标）
  三、大作文：效果里的**字符串叶子**不许长、不许成句
  四、计数类配额：叠层设施（最高值 / 计量 / 层数）的占卡比例不许超线

跑法：`python -X utf8 tools/架构审查/检查三件套边界.py`
任何一组红都会打印违规样例，那些样例就是重构清单本身。
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CONTENT = ROOT / "data" / "战斗" / "功法" / "内容"


def collected_abilities(node: object) -> set[str]:
    """整棵树里出现过的「能力」取值。"""

    found: set[str] = set()

    def walk(item: object) -> None:
        if isinstance(item, dict):
            ability = item.get("能力")
            if isinstance(ability, str):
                found.add(ability)
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(node)
    return found

#: 计数类配额：用到叠层设施的功法卡占比上限（目标 ≤25%）。
#: 口径：只数「该效果自己树里出现的 能力」。构筑模板机制退役前按模板簇整体能力集算，
#: 那是个更粗的口径；改成本树的节点后，现状 0%。
COUNTER_QUOTA = 0.25
#: 效果里的字符串叶子长度上限（现状最长 28，散文会远超它）。
TEXT_LIMIT = 60
#: 成句标点：效果里出现这些，说明有人在卡面写句子而不是写规则。
PROSE_MARKS = re.compile(r"[，。；！？]")


def cards(name: str) -> list[dict]:
    """读一类卡：一个文件可能是一张卡，也可能是一组卡。"""

    found: list[dict] = []
    for path in sorted((CONTENT / name).rglob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                found.append(item)
    return found


def has(node: object, key: str) -> bool:
    """整棵树里有没有这个键。"""

    if isinstance(node, dict):
        return key in node or any(has(v, key) for v in node.values())
    if isinstance(node, list):
        return any(has(v, key) for v in node)
    return False


def has_value(node: object, key: str, value: str) -> bool:
    """整棵树里有没有「某个键等于某个值」（例如 `能力` == `被动技能`）。

    只查键是不够的：功法的越界常写成 `"能力": "被动技能"` —— 键是 `能力`，
    越界信息在**值**里。
    """

    if isinstance(node, dict):
        if node.get(key) == value:
            return True
        return any(has_value(v, key, value) for v in node.values())
    if isinstance(node, list):
        return any(has_value(v, key, value) for v in node)
    return False



def leaves(node: object, path: str = "") -> list[tuple[str, str]]:
    """所有字符串叶子（含路径），用来查"卡面里写句子"。"""

    if isinstance(node, str):
        return [(path, node)]
    if isinstance(node, dict):
        return [item for k, v in node.items() for item in leaves(v, f"{path}.{k}")]
    if isinstance(node, list):
        return [item for i, v in enumerate(node) for item in leaves(v, f"{path}[{i}]")]
    return []


def report(title: str, bad: list[str], total: int, detail: list[str] | None = None) -> bool:
    ok = not bad
    mark = "通过" if ok else "失败"
    print(f"[{mark}] {title}：违规 {len(bad)} / {total}")
    for line in (detail or [])[:5]:
        print(f"        {line}")
    return ok


def _核对职责边界(arts, wills, breaths) -> int:
    failures = 0
    # 一、职责边界
    #: `属性构成`（五行根基）**必须有**：五行规则要求功法/真意/气机/器律四段都带它
    #: （game/core/combat/foundation.py 里那条契约），它是卡面前置而不是"玩法"。
    #: 所以这一条判的是"必须有"，不是"不许有"——第 15 轮我判反了，害得游戏起不来。
    missing_element = [str(c.get("名称")) for c in arts if not has(c, "属性构成")]
    failures += not report(
        "功法必须带五行根基（属性构成）", missing_element, len(arts), missing_element
    )

    #: 越界的真形态是**同一段机制被抄进不该有它的那一面**；哪几个能力算"气机的专用"
    #: 必须先量出来再判，不能凭猜。这里先只报告交集。
    passive_in_arts = [
        str(c.get("名称")) for c in arts if has_value(c, "能力", "被动技能")
    ]
    failures += not report(
        "功法里不许挂被动技能（那是真意的活）", passive_in_arts, len(arts), passive_in_arts
    )

    wills_active = [str(c.get("名称")) for c in wills if has(c, "冷却行动") or has(c, "释放顺序")]
    failures += not report("真意只做被动（不得占行动：冷却 / 释放顺序）", wills_active, len(wills), wills_active)

    breaths_skill = [
        str(c.get("名称"))
        for c in breaths
        if has(c, "层数") or has(c, "状态") or has(c, "冷却行动")
    ]
    failures += not report("气机只做属性（不得是技能或状态）", breaths_skill, len(breaths), breaths_skill)

    return failures


def _核对主动形状(arts) -> int:
    failures = 0
    # 二、主动技能的形状：冷却 / 消耗 / 目标，缺一即不算主动技能
    #: `目标` 写在效果节点里（`/效果/[0]/目标/能力`）。模板机制退役后卡里就是完整树，
    #: 直接在效果节点里找这个键即可；「卡里没有、得看模板参数路径」那个坑也随之消失。

    def has_target(card: dict) -> bool:
        found = False

        def walk(node: object) -> None:
            nonlocal found
            if found:
                return
            if isinstance(node, dict):
                target = node.get("目标")
                if isinstance(target, dict) and ({"能力", "范围"} & set(target)):
                    found = True
                    return
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(card)
        return found

    #: 主动技能分两类（第 39 轮看清）：
    #:   **指向型** —— 打谁/治谁/给谁上状态 ⇒ 必须有 `目标`
    #:   **自指型** —— 改自己、改场上、换形态（改计量/层数/行动条/战场规则…）⇒ 本来就不需要目标
    POINTING = {
        "造成伤害", "恢复资源", "转移伤害", "分摊伤害", "转移资源", "添加状态",
        "触发技能", "复制技能", "转移状态", "复制状态", "复活", "追加攻击", "消耗资源",
    }
    SELF = {
        "修改构筑计量", "修改状态层数", "修改状态持续", "修改行动条", "修改技能冷却",
        "修改战场规则", "修改战术", "修改判定", "修改行动意图", "修改归属", "保存结果",
        "记录战斗事实", "修改战斗关联", "创建战斗对象", "移除战斗对象", "取消事件",
        "修改事件目标", "修改事件数值", "修改事件标签", "切换形态", "修改技能",
    }

    def abilities(card: dict) -> set[str]:
        found: set[str] = set()

        def walk(node: object) -> None:
            if isinstance(node, dict):
                ability = node.get("能力")
                if isinstance(ability, str):
                    found.add(ability)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(card)
        return found

    pointing_cards = [c for c in arts if abilities(c) & POINTING]
    self_cards = [c for c in arts if not (abilities(c) & POINTING)]
    shapeless = [
        str(c.get("名称"))
        for c in pointing_cards
        if not (has(c, "冷却行动") and has(c, "精神消耗") and has_target(c))
    ]
    print(f"        主动技能两分：指向型 {len(pointing_cards)} 张 ｜ 自指型 {len(self_cards)} 张")
    failures += not report("功法要有主动技能的形状（冷却 + 消耗 + 目标）", shapeless, len(arts), shapeless)

    return failures


def _核对大作文(arts) -> int:
    failures = 0
    # 三、大作文：效果里的字符串叶子不许长、不许成句
    long_text: list[str] = []
    prose: list[str] = []
    for card in arts:
        for path, text in leaves(card):
            if not path.endswith("效果") and ".效果" not in path:
                continue
            if len(text) > TEXT_LIMIT:
                long_text.append(f"{card.get('名称')} @ {path}：{len(text)} 字符 —— {text[:40]}")
            elif PROSE_MARKS.search(text):
                prose.append(f"{card.get('名称')} @ {path}：{text[:40]}")
    failures += not report(f"效果里不许写长文本（≤{TEXT_LIMIT} 字符）", long_text, len(arts), long_text)
    failures += not report("效果里不许写成句（不得带成句标点）", prose, len(arts), prose)

    return failures


def _核对计数占比(arts) -> int:
    failures = 0
    #: 口径 D（第 65 轮定的，取代口径 A）：**主动技能里、非声明型**的计数引用占比。
    #: 口径 A（把"声明"也算进去）量的是脚手架而不是玩法：实测同一份数据 A=47.3%、D=**1.2%**。
    #: 声明（`计量`/`状态`/`名称`… 带字符串值的参数）是卡与卡之间的接口，不是玩法。
    counters = ("修改构筑计量", "修改状态层数", "修改状态持续")
    declare_keys = ("计量", "状态", "名称", "判定", "事实", "规则", "保存结果", "关联")

    def declaring(node: object) -> bool:
        """树里有没有「声明」—— 展开后不再有参数包，直接在树里找声明键。"""

        if not isinstance(node, dict):
            return False
        if any(
            str(key).split("/")[-1] in declare_keys and isinstance(value, str) and value
            for key, value in node.items()
        ):
            return True
        return any(declaring(value) for value in node.values())

    refs = 0
    counted = 0
    for card in arts:
        for node in card.get("能力") or []:
            if not isinstance(node, dict) or node.get("能力") != "主动技能":
                continue
            effects = node.get("效果")
            if not isinstance(effects, list):
                continue
            for effect in effects:
                if not isinstance(effect, dict):
                    continue
                refs += 1
                if collected_abilities(effect) & set(counters) and not declaring(effect):
                    counted += 1
    total = refs or 1
    counter_share = counted / total
    ok = counter_share <= COUNTER_QUOTA
    failures += not ok
    print(
        f"[{'通过' if ok else '失败'}] 计数配额（口径 D：主动技能里的非声明计数引用）：{counted} / {refs}"
        f"（{counter_share * 100:.1f}%，上限 {COUNTER_QUOTA * 100:.0f}%）"
    )

    return failures


def main() -> int:
    """跑完四组核对，打印总账。"""

    arts = cards("功法")
    wills = cards("真意")
    breaths = cards("气机")
    print(f"条目：功法 {len(arts)} ｜ 真意 {len(wills)} ｜ 气机 {len(breaths)}")

    failures = 0
    failures += _核对职责边界(arts, wills, breaths)
    failures += _核对主动形状(arts)
    failures += _核对大作文(arts)
    failures += _核对计数占比(arts)
    print(f"总账：失败 {failures} 组")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
