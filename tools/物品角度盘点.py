"""物品作用角度盘点：把涉战物品按「谁的角度、什么时候、干什么」分类，量出重复。

作用角度 = 四维组合（每一维都可从 `使用效果` / `阶段` 树上算出来）：

    介入时机：立即（不含监听）       / 预置（含监听，服下后等时点）
    作用对象：自身 / 队友 / 敌人 / 全体 / 事件相关者
    效果族  ：恢复 / 增益 / 减益 / 控制 / 节奏 / 输出 / 保命 / 召唤 / 规则改写 / 资源转换
    持续    ：瞬时 / 状态 / 整场监听

"每件物品的作用角度都不一样"= 这四个维度的**组合**要散开，而不是全挤在
「立即 · 自身 · 恢复 · 瞬时」这一格上。

**作用对象只数效果落点**：`目标` 字段按父能力的类别分桶（见 `原子能力.json`），
类别 `效果` 的才是落点；类别 `数值` / `条件` / `组合` 的只是读数（读血气、读状态、遍历），
不算作用对象。早先混在一起，读数会把"自身"撑大、把集中点盖住。
"""

from __future__ import annotations

import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SURFACES = (
    ("战丹", "data/物品/炼丹/内容/丹药/战丹/*.json", "使用效果"),
    ("恢复丹", "data/物品/炼丹/内容/丹药/恢复丹/*.json", "使用效果"),
    ("特殊丹", "data/物品/炼丹/内容/丹药/特殊丹/*.json", "使用效果"),
    ("战场环境", "data/战斗/内容/战场环境/*.json", "阶段"),
)

FAMILY = {
    "恢复资源": "恢复", "恢复": "恢复", "获得护盾": "保命", "抵挡致命伤害": "保命",
    "复活": "保命", "添加状态": "增益", "增加状态层数": "增益", "移除状态": "减益",
    "消耗状态层数": "减益", "造成伤害": "输出", "追加攻击": "输出", "转移伤害": "输出",
    "分摊伤害": "输出", "修改行动条": "节奏", "修改技能冷却": "节奏", "修改技能": "节奏",
    "触发技能": "节奏", "复制技能": "节奏", "创建战斗对象": "召唤", "召唤": "召唤",
    "修改事件数值": "规则改写", "修改事件目标": "规则改写", "修改事件标签": "规则改写",
    "取消事件": "规则改写", "转化事件": "规则改写", "修改归属": "规则改写",
    "修改判定": "规则改写", "记录战斗事实": "记录", "记录结果": "记录",
    "消耗资源": "代价", "资源转移": "资源转换", "转移资源": "资源转换",
    "修改构筑计量": "计量", "保存结果": "计量",
    # `读取数值` / `计算数值` **不算效果族**：它们是结构件（读取与算术）。
    # 早先把它们算成「计量」，于是"恢复+计量"那一格其实是"带读数的恢复丹"，
    # 把真正的集中点盖住了——判据本身失真是要比对待改对象更先修的东西。
    "修改状态层数": "增益", "修改状态持续": "增益", "随机执行": "随机",
    "修改战斗关联": "规则改写", "修改形态": "规则改写", "切换形态": "规则改写",
}
SELF = {"自身", "主人"}
ALLY = {"己方", "全部己方", "其他己方", "关联对象"}
FOE = {"敌方", "全部敌方", "当前目标"}
EVENT = {"事件来源", "事件承受者"}
EVERY = {"全体", "全部"}
CONTROL_STATUS = {"控制", "眩晕", "禁锢", "沉默", "嘲讽", "混乱"}
KIND = {str(k): str((v or {}).get("类别") or "") for k, v in json.loads(
    (ROOT / "data/战斗/定义/原子能力.json").read_text(encoding="utf-8")).items()}


def families_of(effects: object) -> tuple[set[str], set[str], set[str], bool, set[str]]:
    families: set[str] = set()
    effect_scopes: set[str] = set()
    read_scopes: set[str] = set()
    has_listener = False
    events: set[str] = set()

    def walk(node: object) -> None:
        nonlocal has_listener
        if isinstance(node, dict):
            ability = str(node.get("能力") or "")
            if ability == "监听事件":
                has_listener = True
                events.add(str(node.get("事件") or ""))
            if ability in FAMILY:
                # `恢复资源` 按资源分：血气/精神是恢复，护盾是保命（`获得护盾` 不是原子能力）。
                if ability == "恢复资源" and str(node.get("资源") or "") == "护盾":
                    families.add("保命")
                else:
                    families.add(FAMILY[ability])
            status = node.get("状态")
            if ability == "添加状态" and isinstance(status, dict):
                name = str(status.get("名称") or "")
                category = str(status.get("类别") or "")
                if status.get("是否控制") or any(k in name for k in CONTROL_STATUS):
                    families.add("控制")
                elif category == "负面":
                    families.add("减益")
            # `目标` 字段按父能力的类别分桶：效果类才是效果落点，数值/条件/组合类只是读数。
            target = node.get("目标")
            if isinstance(target, dict):
                scope = str(target.get("范围") or "")
                if scope:
                    (effect_scopes if KIND.get(ability) == "效果" else read_scopes).add(scope)
            if ability == "选择目标":
                scope = str(node.get("范围") or "")
                if scope:
                    effect_scopes.add(scope)
            for key, value in node.items():
                if key == "目标" and isinstance(value, dict):
                    continue
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(effects)
    return families, effect_scopes, read_scopes, has_listener, events


def object_of(scopes: set[str]) -> str:
    if scopes & EVENT:
        return "事件相关者"
    if scopes & EVERY:
        return "全体"
    if scopes & FOE:
        return "敌人"
    if scopes & ALLY:
        return "队友"
    return "自身"


def main() -> int:
    for name, pattern, field in SURFACES:
        rows: list[tuple[str, str, str, str, str, str]] = []
        for path in sorted(ROOT.glob(pattern)):
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                if not isinstance(entry, dict) or field not in entry:
                    continue
                families, effect_scopes, read_scopes, has_listener, _events = families_of(entry[field])
                effect_type = ""
                if isinstance(entry[field], dict):
                    effect_type = str(entry[field].get("类型") or "")
                rows.append((
                    str(entry.get("编号") or ""),
                    str(entry.get("名称") or ""),
                    "预置" if has_listener else "立即",
                    object_of(effect_scopes) if effect_scopes else (
                        object_of(read_scopes) if read_scopes else "自身"),
                    "+".join(sorted(families)) or effect_type or "（无）",
                    "整场监听" if has_listener else "瞬时",
                ))
        if not rows:
            continue
        combo = collections.Counter(f"{r[2]}·{r[3]}·{r[4]}" for r in rows)
        timing = collections.Counter(r[2] for r in rows)
        obj = collections.Counter(r[3] for r in rows)
        fam = collections.Counter(f for r in rows for f in r[4].split("+"))
        print(f"== {name}：{len(rows)} 件")
        print("   介入时机：" + " ".join(f"{k} {v}" for k, v in timing.most_common()))
        print("   作用对象：" + " ".join(f"{k} {v}" for k, v in obj.most_common()))
        print("   效果族  ：" + " ".join(f"{k} {v}" for k, v in fam.most_common(10)))
        top, count = combo.most_common(1)[0]
        print(f"   角度组合 {len(combo)} 种；最集中的一格「{top}」{count} 件"
              f"（{count / len(rows):.1%}）")
        print(f"   前六格：" + " · ".join(f"{k} {v}" for k, v in combo.most_common(6)))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
