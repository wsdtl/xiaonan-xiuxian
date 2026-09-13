"""物品角度总表：把七类涉战内容逐件列出四维签名，供人过目。

四维（判据来自 `data/战斗/规则/说明.md -> 真意与器律的监听分工` 的同族口径，负责人已确认）：

    时机 A：服用即效 / 战前寄存 / 事件触发 / 节律时点 / 主动施放
    对象 B：自身 / 队友 / 全体己方 / 当前目标 / 事件相关者 / 战场全体
    手段 C：恢复 / 增益 / 减益 / 控制 / 输出 / 节奏 / 保命 / 资源转换 / 规则改写 / 召唤 / 代价
    持续 D：瞬时 / 状态 / 整场 / 计量累积

**对象这一维的口径**：`选择目标` 在数据里只作为 `目标` 字段出现，而带 `目标` 字段的原子分两种
（见 `data/战斗/定义/原子能力.json`）：

- 类别 `效果`（42 个）的 `目标` = 效果落在谁身上 → **作用对象**，进签名；
- 类别 `数值` / `条件` / `组合` / `目标` 的 `目标` = 只是拿来看一眼（读血气、读状态、遍历）
  → **读取对象**，另列一栏，不进签名。

早先把两者混在一起统计，于是"自身"被读数节点撑大（真意自身 8908 就是这么来的），
签名失真。判据本身失真是要比对待改对象更先修的东西。

输出 `data/战斗/内容/物品角度总表.md`。
"""

from __future__ import annotations

import collections
import json
import pathlib

ROOT = pathlib.Path(r"C:\Users\DengXiaonan\Desktop\晓楠修仙")
OUT = ROOT / "data/战斗/内容/物品角度总表.md"

FAMILY = {
    "恢复资源": "恢复", "获得护盾": "保命", "抵挡致命伤害": "保命", "复活": "保命",
    "添加状态": "增益", "增加状态层数": "增益", "消耗状态层数": "减益", "移除状态": "减益",
    "造成伤害": "输出", "追加攻击": "输出", "转移伤害": "输出", "分摊伤害": "输出",
    "修改行动条": "节奏", "修改技能冷却": "节奏", "修改技能": "节奏", "触发技能": "节奏",
    "复制技能": "节奏", "创建战斗对象": "召唤", "修改事件数值": "规则改写",
    "修改事件目标": "规则改写", "修改事件标签": "规则改写", "取消事件": "规则改写",
    "转化事件": "规则改写", "修改归属": "规则改写", "修改判定": "规则改写",
    "消耗资源": "代价", "转移资源": "资源转换", "资源转移": "资源转换",
    "修改构筑计量": "计量", "保存结果": "计量", "修改战斗关联": "规则改写",
    "切换形态": "规则改写", "修改状态层数": "增益", "修改状态持续": "增益",
    # 早先漏掉这三个：用了原子能力却进不了表（120120 大衍观澜丹 / 120054 同袍代劫丹 /
    # 120073 同袍叠城丹）。`记录`类归"规则改写"（它改变后续判定的依据）；
    # `转移状态`归"保命"（把同袍的劫移到自己身上就是护人）。
    "记录战斗事实": "规则改写", "记录结果": "规则改写", "转移状态": "保命",
    "复制状态": "增益", "延长状态": "增益", "回放效果": "规则改写",
    # 气机整类（703 件）的唯一动作。早先不在词表里，于是整类扫出 0 行。
    "固定属性加成": "增益",
}
SELF_SCOPE = {"自身", "主人"}
ALLY_SCOPE = {"己方", "全部己方", "其他己方", "关联对象"}
FOE_SCOPE = {"敌方", "全部敌方", "当前目标"}
EVENT_SCOPE = {"事件来源", "事件承受者"}
EVERY_SCOPE = {"全体", "全部"}
NARRATIVE_EVENTS = {"战斗开始", "战斗结束", "战斗对象入场后", "战斗对象退场后",
                    "战场规则变化后", "形态切换后", "复活后", "行动开始", "行动结束",
                    "行动决策前", "行动决策后"}


ATOMS = {str(k) for k in json.loads(
    (ROOT / "data/战斗/定义/原子能力.json").read_text(encoding="utf-8"))}
KIND = {str(k): str((v or {}).get("类别") or "") for k, v in json.loads(
    (ROOT / "data/战斗/定义/原子能力.json").read_text(encoding="utf-8")).items()}


def uses_atom(node: object) -> bool:
    """范围判据（负责人定）：**只留"使用了战斗原子能力"的内容实例**；配方与人物已去掉。"""
    if isinstance(node, dict):
        if node.get("能力") in ATOMS:
            return True
        return any(uses_atom(value) for value in node.values())
    if isinstance(node, list):
        return any(uses_atom(value) for value in node)
    return False


def analyse(effects: object) -> dict:
    families: set[str] = set()
    effect_scopes: set[str] = set()
    read_scopes: set[str] = set()
    events: set[str] = set()
    listeners = 0
    actives = 0
    layers = 0
    attributes = 0

    def visit(node: object) -> None:
        nonlocal listeners, actives, layers, attributes
        if isinstance(node, dict):
            ability = str(node.get("能力") or "")
            kind = KIND.get(ability, "")
            if ability == "监听事件":
                listeners += 1
                events.add(str(node.get("事件") or ""))
            if ability == "主动技能":
                actives += 1
            if ability == "固定属性加成":
                attributes += 1  # 气机的唯一动作：属性写在节点里，不在 战前状态.属性
            if ability in FAMILY:
                families.add(FAMILY[ability])
            if ability in {"修改构筑计量", "增加状态层数"}:
                layers += 1
            status = node.get("状态")
            if ability == "添加状态" and isinstance(status, dict):
                if status.get("是否控制"):
                    families.add("控制")
                elif str(status.get("类别") or "") == "负面":
                    families.add("减益")
            target = node.get("目标")
            if isinstance(target, dict):
                scope = str(target.get("范围") or "")
                if scope:
                    # 效果类的 `目标` 才是效果落点；数值/条件/组合类的 `目标` 只是读数。
                    (effect_scopes if kind == "效果" else read_scopes).add(scope)
            if ability == "选择目标":
                scope = str(node.get("范围") or "")
                if scope:
                    effect_scopes.add(scope)  # 没挂在 `目标` 字段上的裸选择目标：按落点算
            for key, value in node.items():
                if key == "目标" and isinstance(value, dict):
                    continue  # 已按父能力的类别归桶
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(effects)
    return {"族": families, "作用": effect_scopes, "读取": read_scopes,
            "事件": events, "监听": listeners, "主动": actives, "层": layers,
            "属性": attributes}


def objects(scopes: set[str]) -> str:
    if scopes & EVENT_SCOPE:
        return "事件相关者"
    if scopes & EVERY_SCOPE:
        return "战场全体"
    if scopes & FOE_SCOPE:
        return "当前目标"
    if scopes & ALLY_SCOPE:
        return "队友"
    return "自身"


def timing(info: dict, *, seasonal: bool = False) -> str:
    if seasonal:
        return "节律时点"
    if int(info["主动"]):  # type: ignore[arg-type]
        # 功法是"主动 + 被动"的完整战斗循环；有主动技能就按"战斗里主动施放"算，
        # 否则 600 门功法会全部落进"战前寄存"那一格（那是定值属性的位置）。
        # 这一格的值由负责人确认（原词表只有 服用即效/战前寄存/事件触发/节律时点）。
        return "主动施放"
    if int(info["监听"]):  # type: ignore[arg-type]
        events = set(info["事件"])  # type: ignore[arg-type]
        return "节律时点" if events <= NARRATIVE_EVENTS else "事件触发"
    return "战前寄存"


def duration(info: dict) -> str:
    if int(info["监听"]):  # type: ignore[arg-type]
        return "整场"
    if bool(info.get("属性buff")) or int(info["属性"]):  # type: ignore[arg-type]
        return "整场"  # 纯定值属性（气机、基础档战丹）：装配后并入战斗快照，整场都算
    if int(info["层"]):  # type: ignore[arg-type]
        return "计量累积"
    return "状态"


def rows_for(path: pathlib.Path, field: str | None, *, seasonal: bool = False) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else [data]
    rows: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        payload = entry.get(field) if field else entry
        if payload is None:
            continue
        info = analyse(payload)
        families = set(info["族"])  # type: ignore[arg-type]
        # 范围：只留用了战斗原子能力的实例（配方/人物已按负责人口径去掉）。
        if not (uses_atom(payload) or uses_atom(entry.get("战斗状态"))):
            continue
        # 战前状态的 `属性` 也是"手段"（基础档战丹就是纯属性增益，能力树里什么都没有）。
        for holder in (payload, (payload or {}).get("战前状态") if isinstance(payload, dict) else None,
                       entry.get("战斗状态")):
            if isinstance(holder, dict) and holder.get("属性"):
                families.add("增益")
                info["属性buff"] = True
        # 长期伤势：`行动限制` 是控制向、`匹配` 里的限制也是。
        status = entry.get("战斗状态")
        if isinstance(status, dict):
            if status.get("行动限制"):
                families.add("控制")
            if status.get("类别") == "负面":
                families.add("减益")
            if (entry.get("叠加") or {}).get("层数上限", 1) and int((entry.get("叠加") or {}).get("层数上限") or 1) > 1:
                info["层"] = int(info["层"]) + 1  # type: ignore[arg-type]
        if not families:
            continue
        effect_scopes = set(info["作用"])  # type: ignore[arg-type]
        read_scopes = set(info["读取"])  # type: ignore[arg-type]
        if effect_scopes:
            target = objects(effect_scopes)
        elif read_scopes:
            target = objects(read_scopes)
        else:
            target = "自身"
        rows.append({
            "编号": str(entry.get("编号") or ""),
            "名称": str(entry.get("名称") or ""),
            "时机": timing(info, seasonal=seasonal),
            "对象": target,
            "手段": "+".join(sorted(families)),
            "持续": duration(info),
            "读取": objects(read_scopes) if read_scopes and objects(read_scopes) != target else "—",
            "说明": " ".join(str(entry.get("说明") or "").split())[:46],
            "文件": path.stem,
        })
    return rows


SURFACES: tuple[tuple[str, str, str | None, bool], ...] = (
    ("功法", "data/战斗/内容/功法/功法-*.json", "能力", False),
    ("真意", "data/战斗/内容/真意/真意-*.json", "能力", False),
    ("气机", "data/战斗/内容/气机/气机-*.json", "能力", False),
    ("器律", "data/炼器/内容/器律-*.json", "能力", False),
    ("战丹", "data/炼丹/内容/丹药/战丹/*.json", "使用效果", False),
    ("战场环境", "data/战斗/内容/战场环境/*.json", "阶段", True),
    ("长期伤势", "data/角色/内容/伤势.json", None, False),
)


def collect() -> list[tuple[str, list[dict]]]:
    groups: list[tuple[str, list[dict]]] = []
    for name, pattern, field, seasonal in SURFACES:
        rows: list[dict] = []
        for path in sorted(ROOT.glob(pattern)):
            rows.extend(rows_for(path, field, seasonal=seasonal))
        groups.append((name, rows))
    return groups


def signature(row: dict) -> str:
    return f"{row['时机']}·{row['对象']}·{row['手段']}·{row['持续']}"


def main() -> int:
    groups = collect()

    lines: list[str] = ["# 物品角度总表（待重新设计）", "",
                        "四维：时机 A · 对象 B · 手段 C · 持续 D。", "",
                        "判定目标是**四维签名唯一**（4×6×11×4 = 1056 种），"
                        "**只对战丹与长期伤势生效**——这两类是唯一可以自由设计角度的东西。", "",
                        "**战场环境不参与**：它与地形绑定（`战斗/规则/环境.json` 的 `地表环境来源` "
                        "指向 `地形分区.地形`；`战场环境/说明.md` 要求名称与地点 `地形` 完全一致、"
                        "伤害必须是地理事件的后果），能力就是那片地势的特色，"
                        "不能为了签名不重样去换。", "",
                        "**功法 / 真意 / 气机 / 器律** 只作诊断：看哪些卡长得一样，"
                        "不设唯一性门槛，也不限制以后印卡（四维唯一一旦拿来要求卡，印卡就被锁死）。", "",
                        "`对象` 是**作用对象**（效果落在谁身上）；`读取` 只是看一眼（读血气、"
                        "读状态、遍历），不进签名，只在与作用对象不同时列出。", ""]
    for name, rows in groups:
        if not rows:
            continue
        sig = collections.Counter(signature(r) for r in rows)
        lines.append(f"## {name}（{len(rows)} 件 · 签名 {len(sig)} 种）")
        lines.append("")
        for combo, count in sig.most_common(6):
            lines.append(f"- `{combo}` × {count}")
        lines.append("")
        lines.append("| 编号 | 名称 | 时机 | 对象 | 手段 | 持续 | 读取 | 说明 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
        seen: collections.Counter = collections.Counter()
        for row in sorted(rows, key=lambda r: (r["时机"], r["对象"], r["手段"], r["持续"], r["编号"])):
            combo = signature(row)
            seen[combo] += 1
            mark = f"`×{sig[combo]}`" if seen[combo] == 1 and sig[combo] > 1 else ""
            lines.append(f"| {row['编号']} | {row['名称']} | {row['时机']} | {row['对象']} | "
                         f"{row['手段']} | {row['持续']} {mark} | {row['读取']} | {row['说明']} |")
        lines.append("")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for name, rows in groups:
        if not rows:
            print(f"{name}: 0 件 ✘")
            continue
        sig = collections.Counter(signature(r) for r in rows)
        top = sig.most_common(1)[0]
        reads = sum(1 for r in rows if r["读取"] != "—")
        print(f"{name}: {len(rows)} 件 · 签名 {len(sig)} 种 · 最大同签名 {top[1]} 件（{top[0]}）"
              f" · 读取对象另计 {reads} 件")
    print(f"\n总表写入 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
