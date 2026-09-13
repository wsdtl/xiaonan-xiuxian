"""外来伤势扩容：12 → 20 件，补齐没被接住的匹配面，并给新件装上"战斗中会动"的那一面。

外来伤势靠 `匹配` 接住"战斗结束时仍留在身上的敌方负面状态"。匹配只有三个面
（`原子能力`之外，见 `game/core/injury/service.py` 的 `_matches_external`）：

    属性任一 ∩ 状态改动的属性 · 行动限制任一 ∩ 状态的行动限制 · 标签任一 ∩ 状态的标签

现有 12 件把 11 个会被压低的属性几乎铺满，剩下这些没人接：

| 新件 | 匹配面 | 为什么是它 |
| --- | --- | --- |
| 力竭 | `属性任一 ["攻击"]` | 负面状态里压低 `攻击` 有 36 次，是全库唯一没人接的属性 |
| 崩甲 / 重创 | `属性任一 ["防御"]` / `["伤害减免"]` | 同面分档：优先级排在 `层裂`/`破绽` 之后，只接它们没接住的 |
| 顿滞 | `行动限制任一 ["行动"]` | 现有只接了 `技能`，`行动` 没接 |
| 斑痕 / 灼伤 / 裂骨 / 惊悸 | `标签任一` | 负面状态上有 `破绽`/`持续伤害`/`创伤`/`控制` 四种标签，全都没被用过 |

每件都带监听，四维各占一格（时机·对象·手段·持续）：

    力竭  节律时点 · 自身       · 代价   行动开始时按精神上限失精神
    斑痕  事件触发 · 自身       · 减益   护盾破碎后压受盾加成
    灼伤  节律时点 · 自身       · 输出   行动开始时灼痛自伤
    裂骨  节律时点 · 自身       · 节奏   行动开始时行动条被推
    惊悸  事件触发 · 自身       · 控制   技能施放失败后失守一次
    崩甲  事件触发 · 事件相关者 · 输出   受到伤害后反震事件来源
    重创  事件触发 · 自身       · 输出   受到伤害后按血气上限迸血
    顿滞  节律时点 · 自身       · 代价   行动开始时按精神上限失精神

`蚀脉` 仍是唯一的兜底，优先级从 12 排到 20，排在新件之后。

用法：

    python tools/外来伤势扩容.py --试运行
    python tools/外来伤势扩容.py
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(r"C:\Users\DengXiaonan\Desktop\晓楠修仙")
INJURY_FILE = ROOT / "data/角色/内容/伤势.json"
FALLBACK_ID = "620002"  # 蚀脉：唯一的兜底归类
FALLBACK_PRIORITY = 20

SELF = {"能力": "选择目标", "范围": "自身"}


def read_own(attribute: str, percent: int) -> dict:
    return {"能力": "读取数值", "来源": "自身属性", "属性": attribute,
            "百分比": percent, "最低值": 1}


def costs_spirit(percent: int) -> dict:
    return {"能力": "消耗资源", "目标": SELF, "资源": "精神",
            "数值": read_own("精神上限", percent), "不足时是否失败": False}


def hurts_self(name: str, percent: int) -> dict:
    return {"能力": "造成伤害", "名称": name, "目标": SELF,
            "数值": read_own("血气上限", percent)}


def hurts_source(name: str, percent: int) -> dict:
    return {"能力": "造成伤害", "名称": name,
            "目标": {"能力": "选择目标", "范围": "事件来源"},
            "数值": read_own("血气上限", percent)}


def status(name: str, *, actions: int, attributes: dict | None = None,
           control: bool = False) -> dict:
    body = {"名称": name, "类别": "负面", "剩余行动": actions,
            "持续单位": "状态承受者行动", "属性": dict(attributes or {}),
            "行动限制": [], "标签": ["长期伤势"]}
    if control:
        body["是否控制"] = True
        body["控制基础命中率"] = 100
    return {"能力": "添加状态", "目标": SELF, "状态": body}


def listener(event: str, role: str, effects: list[dict], **extra) -> dict:
    node = {"能力": "监听事件", "事件": event, "观察角色": role,
            "阵营关系": "自身", "效果": effects}
    node.update(extra)
    return node


#: 新增的 8 件外来伤势。`优先级` 排在兜底之前，越靠前越先接。
NEW_INJURIES: tuple[dict, ...] = (
    {
        "编号": "620013", "名称": "力竭", "优先级": 12, "轮数": 2,
        "匹配": {"属性任一": ["攻击"]}, "属性": {"攻击": -8}, "限制": [],
        "监听": [listener("行动开始", "行动者", [costs_spirit(3)],
                        **{"每次行动最多触发": 1})],
    },
    {
        "编号": "620014", "名称": "斑痕", "优先级": 13, "轮数": 1,
        "匹配": {"标签任一": ["破绽"]}, "属性": {"格挡率": -10, "格挡减伤": -6}, "限制": [],
        "监听": [listener("护盾破碎后", "承受者",
                        [status("斑痕迸开", actions=2, attributes={"受盾加成": -8})],
                        **{"每场战斗最多触发": 1})],
    },
    {
        "编号": "620015", "名称": "灼伤", "优先级": 14, "轮数": 2,
        "匹配": {"标签任一": ["持续伤害"]}, "属性": {"受疗加成": -8, "伤害减免": -4}, "限制": [],
        "监听": [listener("行动开始", "行动者", [hurts_self("灼痛", 2)],
                        **{"每次行动最多触发": 1})],
    },
    {
        "编号": "620016", "名称": "裂骨", "优先级": 15, "轮数": 2,
        "匹配": {"标签任一": ["创伤"]}, "属性": {"速度": -6, "闪避率": -6}, "限制": [],
        "监听": [listener("行动开始", "行动者",
                        [{"能力": "修改行动条", "目标": SELF, "方式": "减少", "数值": 20}],
                        **{"每次行动最多触发": 1})],
    },
    {
        "编号": "620017", "名称": "惊悸", "优先级": 16, "轮数": 2,
        "匹配": {"标签任一": ["控制"]}, "属性": {"控制抵抗率": -12}, "限制": [],
        "监听": [listener("技能施放失败后", "来源",
                        [status("惊悸失守", actions=1, control=True)],
                        **{"每场战斗最多触发": 1})],
    },
    {
        "编号": "620018", "名称": "崩甲", "优先级": 17, "轮数": 2,
        "匹配": {"属性任一": ["防御"]}, "属性": {"防御": -10}, "限制": [],
        "监听": [listener("受到伤害后", "承受者", [hurts_source("甲崩反震", 2)],
                        **{"每场战斗最多触发": 2})],
    },
    {
        "编号": "620019", "名称": "重创", "优先级": 18, "轮数": 3,
        "匹配": {"属性任一": ["伤害减免"]}, "属性": {"伤害减免": -20}, "限制": [],
        "监听": [listener("受到伤害后", "承受者", [hurts_self("重创迸血", 3)],
                        **{"每场战斗最多触发": 1})],
    },
    {
        "编号": "620020", "名称": "顿滞", "优先级": 19, "轮数": 1,
        "匹配": {"行动限制任一": ["行动"]}, "属性": {}, "限制": ["行动"],
        "监听": [listener("行动开始", "行动者", [costs_spirit(2)],
                        **{"每次行动最多触发": 1})],
    },
)


def build(spec: dict) -> dict:
    return {
        "编号": spec["编号"],
        "名称": spec["名称"],
        "说明": f"[{spec['名称']}]是修行或交锋留下的长期伤势，会持续影响角色状态。\n",
        "来源类别": "外来伤势",
        "匹配状态": spec["名称"],
        "匹配优先级": spec["优先级"],
        "匹配": spec["匹配"],
        "战斗状态": {
            "类别": "负面",
            "剩余行动": 3,
            "持续单位": "状态承受者行动",
            "属性": dict(spec["属性"]),
            "行动限制": list(spec["限制"]),
            "标签": ["长期伤势"],
            "监听": spec["监听"],
        },
        "叠加": {"层数上限": 3},
        "治疗": {"每层所需轮数": spec["轮数"], "优先级": 20},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--试运行", action="store_true", help="只报会改什么")
    args = parser.parse_args()

    injuries: list[dict] = json.loads(INJURY_FILE.read_text(encoding="utf-8"))
    existing = {str(item["编号"]) for item in injuries}
    added = [build(spec) for spec in NEW_INJURIES if str(spec["编号"]) not in existing]

    fallback = next((item for item in injuries
                     if str(item.get("编号")) == FALLBACK_ID), None)
    if fallback is None:
        raise SystemExit(f"找不到兜底伤势 {FALLBACK_ID}")
    before = fallback.get("匹配优先级")
    external = sum(1 for item in injuries if str(item.get("来源类别")) == "外来伤势")

    print(f"外来伤势 {external} 件 → {external + len(added)} 件")
    for entry in added:
        print(f"   {entry['编号']} {entry['名称']:<4} 优先级={entry['匹配优先级']} "
              f"匹配={json.dumps(entry['匹配'], ensure_ascii=False)} "
              f"监听={entry['战斗状态']['监听'][0]['事件']}")
    print(f"兜底 {FALLBACK_ID} 的优先级 {before} → {FALLBACK_PRIORITY}（排到新件之后）")
    if args.试运行:
        print("\n（试运行，未落盘）")
        return 0

    fallback["匹配优先级"] = FALLBACK_PRIORITY
    INJURY_FILE.write_text(
        json.dumps(injuries + added, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n已写入 {INJURY_FILE.relative_to(ROOT)}（共 {len(injuries) + len(added)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
