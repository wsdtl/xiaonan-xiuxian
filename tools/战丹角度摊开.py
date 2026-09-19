"""战丹角度摊开：同签名堆（≥3 件）按药性补一件本行之外的机制，把四维位置摊开。

**不动触发面**：13 个药性文件是按监听时点分工的（控制=禁制面、攻伐=交击判定面、
阵势=护盾与轮转面……），触发事件是药性身份，一件都不改。

改的是**手段与对象**：同一格里挤着的丹药，按它所属药性补一件"本来该有"的机制——
合炼补计量、劫丹补保命、资源补节奏、控制补减益……每个药性有一张优先表，
取表里第一个**它现在还没有**的机制，挂在它第一条监听的效果末尾。

对象也按强度分：同契 / 援护 / 合炼 的高强度丹（强度 ≥ 4）把恢复对象从自身改到己方，
低强度保持自身。

    python tools/战丹角度摊开.py --试运行
    python tools/战丹角度摊开.py
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PILLS = ROOT / "data/物品/炼丹/内容/丹药/战丹"

FAMILY = {
    "恢复资源": "恢复", "获得护盾": "保命", "抵挡致命伤害": "保命", "复活": "保命",
    "添加状态": "增益", "增加状态层数": "增益", "消耗状态层数": "减益", "移除状态": "减益",
    "造成伤害": "输出", "追加攻击": "输出", "转移伤害": "输出", "分摊伤害": "输出",
    "修改行动条": "节奏", "修改技能冷却": "节奏", "修改技能": "节奏", "触发技能": "节奏",
    "复制技能": "节奏", "创建战斗对象": "召唤", "修改事件数值": "规则改写",
    "修改事件目标": "规则改写", "取消事件": "规则改写", "转化事件": "规则改写",
    "修改判定": "规则改写", "消耗资源": "代价", "转移资源": "资源转换",
    "修改构筑计量": "计量", "保存结果": "计量", "记录战斗事实": "规则改写",
    "修改归属": "规则改写", "切换形态": "规则改写", "修改状态层数": "增益",
    "修改状态持续": "增益", "复制状态": "增益", "延长状态": "增益", "回放效果": "规则改写",
    "转移状态": "保命",
}
ALLY = {"己方", "全部己方", "其他己方", "关联对象"}
FOE = {"敌方", "全部敌方", "当前目标"}
EVENT = {"事件来源", "事件承受者"}
EVERY = {"全体", "全部"}
NARRATIVE = {"战斗开始", "战斗结束", "战斗对象入场后", "战斗对象退场后",
             "战场规则变化后", "形态切换后", "复活后", "行动开始", "行动结束",
             "行动决策前", "行动决策后"}

#: 每个药性的机制优先表：取第一个它还没有的。同一格里有多枚时**组内轮转**，
#: 否则同药性的几枚会补上同一件，又挤回一格（第一版就踩了这个坑）。
PREFERENCE: dict[str, tuple[str, ...]] = {
    "攻伐": ("输出", "节奏", "减益", "计量", "保命"),
    "援护": ("保命", "恢复", "增益", "节奏", "计量"),
    "绝境": ("保命", "输出", "计量", "代价", "节奏"),
    "资源": ("节奏", "计量", "增益", "代价", "保命"),
    "阵势": ("节奏", "规则改写", "保命", "计量", "增益"),
    "应变": ("节奏", "增益", "输出", "计量", "保命"),
    "控制": ("减益", "控制", "节奏", "计量", "代价"),
    "克制": ("规则改写", "减益", "输出", "代价", "保命"),
    "合炼": ("计量", "增益", "节奏", "保命", "输出"),
    "同契": ("保命", "增益", "节奏", "计量", "恢复"),
    "劫丹": ("保命", "代价", "输出", "节奏", "计量"),
    "天机": ("规则改写", "计量", "增益", "保命", "节奏"),
    "基础": (),
}
#: 高强度丹把恢复对象改到己方（同袍向的三个药性）。
PARTY_AT = {"同契", "援护", "合炼"}


def nodes(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from nodes(value)


def families(entry: dict) -> set[str]:
    found = {FAMILY[str(nd.get("能力"))] for nd in nodes(entry.get("使用效果"))
             if nd.get("能力") in FAMILY}
    payload = entry.get("使用效果") or {}
    holder = payload.get("战前状态")
    if isinstance(holder, dict) and holder.get("属性"):
        found.add("增益")
    return found


def scopes(entry: dict) -> set[str]:
    found = set()
    for nd in nodes(entry.get("使用效果")):
        if nd.get("能力") == "选择目标":
            found.add(str(nd.get("范围")))
        target = nd.get("目标")
        if isinstance(target, dict) and target.get("范围"):
            found.add(str(target["范围"]))
    return found


def signature(entry: dict) -> str:
    payload = entry.get("使用效果") or {}
    events = {str(nd.get("事件")) for nd in nodes(payload) if nd.get("能力") == "监听事件"}
    layers = sum(1 for nd in nodes(payload)
                 if nd.get("能力") in {"修改构筑计量", "增加状态层数"})
    if events:
        timing = "节律时点" if events <= NARRATIVE else "事件触发"
    else:
        timing = "战前寄存"
    found = scopes(entry)
    if found & EVENT:
        obj = "事件相关者"
    elif found & EVERY:
        obj = "战场全体"
    elif found & FOE:
        obj = "当前目标"
    elif found & ALLY:
        obj = "队友"
    else:
        obj = "自身"
    duration = "整场" if events else ("计量累积" if layers else "状态")
    return f"{timing}·{obj}·{'+'.join(sorted(families(entry))) or '属性'}·{duration}"


def self_target() -> dict:
    return {"能力": "选择目标", "范围": "自身"}


def own(attribute: str, percent: int) -> dict:
    return {"能力": "读取数值", "来源": "自身属性", "属性": attribute,
            "百分比": percent, "最低值": 1}


def free_name(base: str, taken: set[str]) -> str:
    """全库词条池（计量 / 状态 / 事实 / 战前状态）里的名字不能重。

    第一版直接用「丹名前两字 + 固定后缀」，撞上了别的实体的同名状态
    （`玄冰丹痕` 既当计量又当状态），单元测试把这它挡下来了。这里逐个后缀试到不撞为止，
    并把选中的名字登记进 taken，避免本次运行内部再撞。
    """

    for suffix in ("", "纹", "印", "痕", "兆", "契", "隙", "烬", "缕", "丝"):
        candidate = base + suffix
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    raise SystemExit(f"名字用尽：{base}")


def name_pool() -> set[str]:
    """全库已用的词条名：计量、状态、事实、规则、战前状态。"""

    taken: set[str] = set()
    for path in ROOT.glob("data/**/*.json"):
        if "/定义/" in path.as_posix():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for node in nodes(document):
            ability = node.get("能力")
            if not isinstance(ability, str):  # 有些定义体把 `能力` 写成数组，跳过
                continue
            if ability == "修改构筑计量" and node.get("计量"):
                taken.add(str(node["计量"]))
            elif ability == "添加状态" and isinstance(node.get("状态"), dict):
                name = node["状态"].get("名称")
                if name:
                    taken.add(str(name))
            elif ability in {"记录战斗事实", "保存结果", "修改战场规则"} and node.get("名称"):
                taken.add(str(node["名称"]))
            holder = node.get("战前状态")
            if isinstance(holder, dict) and holder.get("名称"):
                taken.add(str(holder["名称"]))
    return taken


def extra(family: str, entry: dict, taken: set[str]) -> dict | None:
    """按机制造一条效果；名字带丹名前两字，并保证不撞全库词条池。"""

    tag = str(entry["名称"])[:2]
    if family == "输出":
        return {"能力": "造成伤害", "名称": free_name(f"{tag}追击", taken),
                "目标": {"能力": "选择目标", "范围": "当前目标"},
                "数值": {"能力": "读取数值", "来源": "自身属性", "属性": "攻击",
                         "百分比": 55, "最低值": 1}}
    if family == "节奏":
        return {"能力": "修改行动条", "目标": self_target(), "方式": "增加", "数值": 12}
    if family == "减益":
        return {"能力": "添加状态", "目标": {"能力": "选择目标", "范围": "事件来源"},
                "状态": {"名称": free_name(f"{tag}禁痕", taken), "类别": "负面",
                         "剩余行动": 2, "持续单位": "状态承受者行动",
                         "属性": {"命中率": -8}, "行动限制": [], "标签": ["丹药"]}}
    if family == "控制":
        return {"能力": "添加状态", "目标": {"能力": "选择目标", "范围": "事件来源"},
                "状态": {"名称": free_name(f"{tag}锁纹", taken), "类别": "负面",
                         "剩余行动": 1, "持续单位": "状态承受者行动", "属性": {},
                         "行动限制": [], "标签": ["丹药"], "是否控制": True,
                         "控制基础命中率": 100}}
    if family == "增益":
        return {"能力": "添加状态", "目标": self_target(),
                "状态": {"名称": free_name(f"{tag}灵印", taken), "类别": "正面",
                         "剩余行动": 2, "持续单位": "状态承受者行动",
                         "属性": {"速度": 6}, "行动限制": [], "标签": ["丹药"]}}
    if family == "保命":
        # `获得护盾` 不是原子能力（第一版用了它，真实对局直接抛错）；护盾走 `恢复资源`。
        return {"能力": "恢复资源", "目标": self_target(), "资源": "护盾",
                "数值": own("血气上限", 15)}
    if family == "计量":
        return {"能力": "修改构筑计量", "目标": self_target(),
                "计量": free_name(f"{tag}丹痕", taken), "方式": "增加", "数值": 1, "最高值": 8}
    if family == "代价":
        return {"能力": "消耗资源", "目标": self_target(), "资源": "精神",
                "数值": own("精神上限", 3), "不足时是否失败": False}
    if family == "规则改写":
        return {"能力": "记录战斗事实", "归属": self_target(),
                "名称": free_name(f"{tag}丹机", taken), "值": 1, "方式": "累加"}
    if family == "恢复":
        return {"能力": "恢复资源", "目标": {"能力": "选择目标", "范围": "己方"},
                "资源": "血气", "数值": own("血气上限", 10)}
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--试运行", action="store_true")
    parser.add_argument("--上限", type=int, default=3, help="只摊开这一件数以上的格子")
    args = parser.parse_args()

    files = sorted(PILLS.glob("*.json"))
    documents = {path: json.loads(path.read_text(encoding="utf-8")) for path in files}
    crowded = collections.Counter(signature(entry) for path in files
                                  for entry in documents[path])
    before = len(crowded)

    # 先把要改的按（药性 · 原签名）分组，组内轮转补不同机制。
    pending: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    theme_of: dict[int, str] = {}
    for path in files:
        theme = path.stem.split("-")[1]
        for entry in documents[path]:
            if not (entry.get("使用效果") or {}).get("监听"):
                continue
            sig = signature(entry)
            if crowded[sig] < args.上限 or not PREFERENCE.get(theme):
                continue
            pending[(theme, sig)].append(entry)
            theme_of[id(entry)] = theme

    touched = 0
    table: list[str] = []
    taken = name_pool()
    for (theme, sig), group in sorted(pending.items()):
        have = families(group[0])
        candidates = [family for family in PREFERENCE[theme] if family not in have]
        if not candidates:
            continue
        for index, entry in enumerate(group):
            pick = candidates[index % len(candidates)]
            node = extra(pick, entry, taken)
            if node is None:
                continue
            entry["使用效果"]["监听"][0]["效果"].append(node)
            if int(entry.get("强度") or 0) >= 4 and theme in PARTY_AT:
                for effect in nodes(entry["使用效果"]["监听"][0]["效果"]):
                    if effect.get("能力") == "恢复资源":
                        effect["目标"] = {"能力": "选择目标", "范围": "己方"}
                        break
            touched += 1
            table.append(f"  {entry['编号']} {entry['名称']:<7}({theme}) {sig} → 补 {pick}")

    after = collections.Counter(signature(entry) for path in files
                                for entry in documents[path])
    print(f"摊开前：{sum(crowded.values())} 件 / {before} 格 · 最大 {max(crowded.values())} 件")
    print(f"摊开后：{sum(after.values())} 件 / {len(after)} 格 · 最大 {max(after.values())} 件")
    print(f"改动 {touched} 枚")
    for line in table[:12]:
        print(line)
    if touched > 12:
        print(f"  …… 其余 {touched - 12} 枚同类")
    print("\n摊开后仍 ≥3 件的格子：")
    for combo, count in after.most_common(6):
        if count >= 3:
            print(f"  ×{count} {combo}")
    if args.试运行:
        print("\n（试运行，未落盘）")
        return 0

    for path, document in documents.items():
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"\n已写入 {len(documents)} 个战丹文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
