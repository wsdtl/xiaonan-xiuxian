"""物品角度总表：把涉战物品（战丹 · 战场环境 · 长期伤势）逐件列出四维签名，供人过目。

四维（判据来自 `data/战斗/规则/说明.md -> 真意与器律的监听分工` 的同族口径，负责人已确认）：

    时机 A：服用即效 / 战前寄存 / 事件触发 / 节律时点
    对象 B：自身 / 队友 / 全体己方 / 当前目标 / 事件相关者 / 战场全体
    手段 C：恢复 / 增益 / 减益 / 控制 / 输出 / 节奏 / 保命 / 资源转换 / 规则改写 / 召唤 / 代价
    持续 D：瞬时 / 状态 / 整场 / 计量累积

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
}
SELF_SCOPE = {"自身", "主人"}
ALLY_SCOPE = {"己方", "全部己方", "其他己方", "关联对象"}
FOE_SCOPE = {"敌方", "全部敌方", "当前目标"}
EVENT_SCOPE = {"事件来源", "事件承受者"}
EVERY_SCOPE = {"全体", "全部"}
NARRATIVE_EVENTS = {"战斗开始", "战斗结束", "战斗对象入场后", "战斗对象退场后",
                    "战场规则变化后", "形态切换后", "复活后", "行动开始", "行动结束",
                    "行动决策前", "行动决策后"}


def analyse(effects: object) -> dict[str, set[str] | bool | int]:
    families: set[str] = set()
    scopes: set[str] = set()
    events: set[str] = set()
    listeners = 0
    layers = 0

    def walk(node: object) -> None:
        nonlocal listeners, layers
        if isinstance(node, dict):
            ability = str(node.get("能力") or "")
            if ability == "监听事件":
                listeners += 1
                events.add(str(node.get("事件") or ""))
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
            scope = None
            if ability == "选择目标":
                scope = str(node.get("范围") or "")
            elif isinstance(node.get("目标"), dict):
                scope = str(node["目标"].get("范围") or "")
            if scope:
                scopes.add(scope)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(effects)
    return {"族": families, "范围": scopes, "事件": events, "监听": listeners, "层": layers}


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
    if int(info["监听"]):  # type: ignore[arg-type]
        events = set(info["事件"])  # type: ignore[arg-type]
        return "节律时点" if events <= NARRATIVE_EVENTS else "事件触发"
    return "战前寄存"


def duration(info: dict) -> str:
    if int(info["监听"]):  # type: ignore[arg-type]
        return "整场"
    if int(info["层"]):  # type: ignore[arg-type]
        return "计量累积"
    return "状态"


def rows_for(path: pathlib.Path, field: str, *, seasonal: bool = False) -> list[dict]:
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
        # 战前状态的 `属性` 也是"手段"（基础档战丹就是纯属性增益，能力树里什么都没有）。
        for holder in (payload, (payload or {}).get("战前状态") if isinstance(payload, dict) else None,
                       entry.get("战斗状态")):
            if isinstance(holder, dict) and holder.get("属性"):
                families.add("增益")
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
        rows.append({
            "编号": str(entry.get("编号") or ""),
            "名称": str(entry.get("名称") or ""),
            "时机": timing(info, seasonal=seasonal),
            "对象": objects(info["范围"]),  # type: ignore[arg-type]
            "手段": "+".join(sorted(families)),
            "持续": duration(info),
            "说明": " ".join(str(entry.get("说明") or "").split())[:46],
            "文件": path.stem,
        })
    return rows


def main() -> int:
    groups: list[tuple[str, list[dict]]] = []
    战丹: list[dict] = []
    for path in sorted(ROOT.glob("data/炼丹/内容/丹药/战丹/*.json")):
        战丹.extend(rows_for(path, "使用效果"))
    groups.append(("战丹", 战丹))

    环境: list[dict] = []
    for path in sorted(ROOT.glob("data/战斗/内容/战场环境/*.json")):
        环境.extend(rows_for(path, "阶段", seasonal=True))
    groups.append(("战场环境", 环境))

    伤势: list[dict] = []
    for path in sorted(ROOT.glob("data/角色/内容/伤势.json")):
        伤势.extend(rows_for(path, None))
    groups.append(("长期伤势", 伤势))

    lines: list[str] = ["# 物品角度总表（待重新设计）", "",
                        "四维：时机 A · 对象 B · 手段 C · 持续 D；"
                        "判定目标是**四维签名唯一**（4×6×11×4 = 1056 种）。", ""]
    for name, rows in groups:
        if not rows:
            continue
        sig = collections.Counter(f"{r['时机']}·{r['对象']}·{r['手段']}·{r['持续']}" for r in rows)
        lines.append(f"## {name}（{len(rows)} 件 · 签名 {len(sig)} 种）")
        lines.append("")
        for combo, count in sig.most_common(6):
            lines.append(f"- `{combo}` × {count}")
        lines.append("")
        lines.append("| 编号 | 名称 | 时机 | 对象 | 手段 | 持续 | 说明 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        seen: collections.Counter = collections.Counter()
        for row in sorted(rows, key=lambda r: (r["时机"], r["对象"], r["手段"], r["持续"], r["编号"])):
            combo = f"{row['时机']}·{row['对象']}·{row['手段']}·{row['持续']}"
            seen[combo] += 1
            mark = f"`×{sig[combo]}`" if seen[combo] == 1 and sig[combo] > 1 else ""
            lines.append(f"| {row['编号']} | {row['名称']} | {row['时机']} | {row['对象']} | "
                         f"{row['手段']} | {row['持续']} {mark} | {row['说明']} |")
        lines.append("")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for name, rows in groups:
        sig = collections.Counter(f"{r['时机']}·{r['对象']}·{r['手段']}·{r['持续']}" for r in rows)
        top = sig.most_common(1)[0] if sig else ("", 0)
        print(f"{name}: {len(rows)} 件 · 签名 {len(sig)} 种 · 最大同签名 {top[1]} 件（{top[0]}）")
    print(f"\n总表写入 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
