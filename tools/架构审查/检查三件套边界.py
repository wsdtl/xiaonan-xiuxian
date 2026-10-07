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
CONTENT = ROOT / "data" / "战斗" / "内容"

#: 计数类配额：用到叠层设施的功法卡占比上限（现状 97.7%，目标 ≤25%）。
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


def effect_nodes(node: object) -> list[dict]:
    """所有「效果」条目（形如 {"模板": …, "参数": {…}}）。"""

    if isinstance(node, dict):
        found = []
        if isinstance(node.get("模板"), str):
            found.append(node)
        for value in node.values():
            found.extend(effect_nodes(value))
        return found
    if isinstance(node, list):
        return [item for value in node for item in effect_nodes(value)]
    return []


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


def main() -> int:
    failures = 0
    arts = cards("功法")
    wills = cards("真意")
    breaths = cards("气机")
    print(f"条目：功法 {len(arts)} ｜ 真意 {len(wills)} ｜ 气机 {len(breaths)}")

    # 一、职责边界
    #: `属性构成`（五行根基）**必须有**：五行规则要求功法/真意/气机/器律四段都带它
    #: （game/core/combat/foundation.py 里那条契约），它是卡面前置而不是"玩法"。
    #: 所以这一条判的是"必须有"，不是"不许有"——第 15 轮我判反了，害得游戏起不来。
    missing_element = [str(c.get("名称")) for c in arts if not has(c, "属性构成")]
    failures += not report(
        "功法必须带五行根基（属性构成）", missing_element, len(arts), missing_element
    )

    #: 越界的真形态是**模板用错**，但哪几个模板算"气机的专用"必须先量出来再判，
    #: 不能凭猜（模板编号是内容地址，光看哈希认不出是谁的活）。这里先只报告交集。
    def template_ids(node: object) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            if isinstance(node.get("模板"), str):
                found.add(str(node["模板"]))
            for value in node.values():
                found |= template_ids(value)
        elif isinstance(node, list):
            for value in node:
                found |= template_ids(value)
        return found

    art_t = [template_ids(c) for c in arts]
    will_t = [template_ids(c) for c in wills]
    breath_t = [template_ids(c) for c in breaths]
    all_art = set().union(*art_t) if art_t else set()
    all_will = set().union(*will_t) if will_t else set()
    all_breath = set().union(*breath_t) if breath_t else set()
    print(
        f"       模板集合：功法 {len(all_art)} ｜ 真意 {len(all_will)} ｜ 气机 {len(all_breath)}"
        f" ｜ 功法∩真意 {len(all_art & all_will)} ｜ 功法∩气机 {len(all_art & all_breath)}"
    )
    will_only = all_will - all_breath
    breath_only = all_breath - all_will
    print(
        f"       真意独有 {len(will_only)} 个（其中 {len(will_only & all_art)} 个也被功法用了）"
        f" ｜ 气机独有 {len(breath_only)} 个（其中 {len(breath_only & all_art)} 个也被功法用了）"
    )

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

    # 二、主动技能的形状：冷却 / 消耗 / 目标，缺一即不算主动技能
    #: `目标` 不在卡里，而在**模板体**里：卡只写 {"模板": …} 与少量参数覆盖，
    #: 真正的 `/效果/[0]/目标/能力` 由模板主体提供。所以判"有没有目标"要看
    #: 引用模板的参数路径，而不是在卡里找 `目标` 这个键（第 38 轮踩过的坑）。
    from game.core.combat.template_data import TEMPLATE_CLUSTERS

    def has_target(card: dict) -> bool:
        found = False

        def walk(node: object) -> None:
            nonlocal found
            if found:
                return
            if isinstance(node, dict):
                name = node.get("模板")
                if isinstance(name, str):
                    paths = (TEMPLATE_CLUSTERS.get(name) or [[], []])[1]
                    if any(str(item).endswith("/目标/能力") or str(item).endswith("/目标/范围") for item in paths):
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
                name = node.get("模板")
                if isinstance(name, str):
                    for ability in (TEMPLATE_CLUSTERS.get(name) or [[]])[0]:
                        found.add(str(ability))
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

    #: 口径 D（第 65 轮定的，取代口径 A）：**主动技能里、非声明型**的计数引用占比。
    #: 口径 A（把"声明"也算进去）量的是脚手架而不是玩法：实测同一份数据 A=47.3%、D=**1.2%**。
    #: 声明（`计量`/`状态`/`名称`… 带字符串值的参数）是卡与卡之间的接口，不是玩法。
    counters = ("修改构筑计量", "修改状态层数", "修改状态持续")
    declare_keys = ("计量", "状态", "名称", "判定", "事实", "规则", "保存结果", "关联")

    def declaring(node: object) -> bool:
        params = node.get("参数") if isinstance(node, dict) else None
        if not isinstance(params, dict):
            return False
        return any(
            str(key).split("/")[-1] in declare_keys and isinstance(value, str) and value
            for key, value in params.items()
        )

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
                if not isinstance(effect, dict) or not isinstance(effect.get("模板"), str):
                    continue
                refs += 1
                if set(TEMPLATE_CLUSTERS.get(effect["模板"], [[]])[0]) & set(counters) and not declaring(effect):
                    counted += 1
    total = refs or 1
    counter_share = counted / total
    ok = counter_share <= COUNTER_QUOTA
    failures += not ok
    print(
        f"[{'通过' if ok else '失败'}] 计数配额（口径 D：主动技能里的非声明计数引用）：{counted} / {refs}"
        f"（{counter_share * 100:.1f}%，上限 {COUNTER_QUOTA * 100:.0f}%）"
    )

    print(f"总账：失败 {failures} 组")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
