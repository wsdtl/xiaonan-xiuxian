"""长期伤势扩容：境界自生的异状 6 → 12 种（20 境界 = 240 件），并把第 6 种按境界层次拆开。

负责人给定「先用一半」：每境界 12 种。原 6 种保留（5 个纯面板方向 + 1 个会动的
`行动命中向`），新增 6 个方向，每个方向在四维上各占一个不同的位置：

| 新增 | 方向 | 时机（监听谁的事） | 对象 | 手段 | 做法 |
| --- | --- | --- | --- | --- | --- |
| 第 7 种 | 迸裂 | 事件触发（`受到伤害后`） | 自身 | 输出 | 按血气上限的百分比自伤 |
| 第 8 种 | 反噬 | 事件触发（`受到伤害后`） | 事件相关者 | 输出 | 对事件来源造成伤害 |
| 第 9 种 | 淤积 | 事件触发（`造成伤害后`） | 自身 | 计量 | 累计量，满 3 层发作一次 |
| 第 10 种 | 滞涩 | 事件触发（`技能施放后`） | 自身 | 节奏 | 令可用技能冷却 +1 |
| 第 11 种 | 渗漏 | 节律时点（`行动开始`） | 自身 | 代价 | 按精神上限扣精神 |
| 第 12 种 | 余烬 | 事件触发（`技能施放失败后`） | 自身 | 控制 | 短暂失控一次 |

第 6 种（原来 20 个境界一个样的那件）按境界层次改，不再全库同模：

| 层次 | 境界 | 复发时 |
| --- | --- | --- |
| 肉身 | 1-4 境 | 保留原两套（行动条被推 / 旧伤牵动自伤） |
| 灵机 | 5-8 境 | 压 `受疗加成`、`精神恢复` |
| 丹府 | 9-12 境 | 拖可用技能的冷却 |
| 神魂 | 13-16 境 | 短暂失控（`是否控制`） |
| 天阶 | 17-20 境 | 按精神上限扣精神 |

规则同步：`角色/规则/伤势/长期伤势.json` 的 `每境界自生数量` 6 → 12。

用法：

    python tools/伤势扩容.py --试运行     # 只报会改什么
    python tools/伤势扩容.py              # 落盘
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(r"C:\Users\DengXiaonan\Desktop\晓楠修仙")
INJURY_FILE = ROOT / "data/角色/内容/伤势.json"
REALM_FILE = ROOT / "data/角色/内容/境界.json"
RULE_FILE = ROOT / "data/角色/规则/伤势/长期伤势.json"

#: 新增六个方向的词与监听时点。`次数` 按境界层次递增（越高境界越容易复发）。
DIRECTIONS: dict[int, dict] = {
    7: {"词": "迸裂", "事件": "受到伤害后", "角色": "来源", "次数": 2, "观察": "承受者"},
    8: {"词": "反噬", "事件": "受到伤害后", "角色": "来源", "次数": 3, "观察": "承受者"},
    9: {"词": "淤积", "事件": "造成伤害后", "角色": "来源", "次数": 3, "观察": "来源"},
    10: {"词": "滞涩", "事件": "技能施放后", "角色": "来源", "次数": 3, "观察": "来源"},
    11: {"词": "渗漏", "事件": "资源恢复后", "角色": "来源", "次数": 3, "观察": "来源"},
    12: {"词": "余烬", "事件": "技能施放失败后", "角色": "来源", "次数": 2, "观察": "来源"},
}
#: 第 6 种按层次换的那一下；1-4 境保持不变，所以不在这里。
LAYER_SIXTH: dict[int, str] = {2: "灵滞", 3: "府漏", 4: "神摇", 5: "基虚"}


def tier_of(realm_index: int) -> int:
    """境界层次：每 4 个境界一层，共 5 层。"""

    return (realm_index - 1) // 4 + 1


def rounds_of(tier: int) -> int:
    """疗伤轮数：越高境界的伤越难养。"""

    return 1 if tier <= 2 else (2 if tier == 3 else 3)


def self_target() -> dict:
    return {"能力": "选择目标", "范围": "自身"}


def read_own(attribute: str, percent: int) -> dict:
    return {"能力": "读取数值", "来源": "自身属性", "属性": attribute,
            "百分比": percent, "最低值": 1}


def listener(event: str, role: str, effects: list[dict], **extra) -> dict:
    node = {"能力": "监听事件", "事件": event, "观察角色": role,
            "阵营关系": "自身", "效果": effects}
    node.update(extra)
    return node


def damage(name: str, target: dict, value: object) -> dict:
    return {"能力": "造成伤害", "名称": name, "目标": target, "数值": value}


def status(name: str, *, actions: int, attributes: dict | None = None,
           control: bool = False) -> dict:
    body = {"名称": name, "类别": "负面", "剩余行动": actions,
            "持续单位": "状态承受者行动", "属性": dict(attributes or {}),
            "行动限制": [], "标签": ["长期伤势"]}
    if control:
        body["是否控制"] = True
        body["控制基础命中率"] = 100
    return {"能力": "添加状态", "目标": self_target(), "状态": body}


def sixth_effect(tier: int, realm_name: str) -> list[dict] | None:
    """第 6 种（会动的那件）按层次换的效果；返回 None 表示保留原状。"""

    if tier == 1:
        return None
    if tier == 2:
        return [status(f"{realm_name}灵滞", actions=2,
                       attributes={"受疗加成": -6, "精神恢复": -6})]
    if tier == 3:
        return [{"能力": "修改技能冷却", "目标": self_target(),
                 "技能": {"能力": "选择技能", "范围": "可用技能", "排序": "冷却从低到高", "数量": 1},
                 "方式": "增加", "数值": 1}]
    if tier == 4:
        return [status(f"{realm_name}神摇", actions=1, control=True)]
    return [{"能力": "消耗资源", "目标": self_target(), "资源": "精神",
             "数值": read_own("精神上限", 3), "不足时是否失败": False}]


def new_entry(realm_index: int, realm_id: str, realm_name: str, index: int) -> dict:
    """造一件新增的自生异状。"""

    tier = tier_of(realm_index)
    spec = DIRECTIONS[index]
    word = str(spec["词"])
    scale = tier
    if index == 7:
        effects = [damage("旧伤迸裂", self_target(), read_own("血气上限", 3 + scale))]
        listens = [listener("受到伤害后", "承受者", effects, **{"每场战斗最多触发": 2})]
    elif index == 8:
        effects = [damage("积怨反噬", {"能力": "选择目标", "范围": "事件来源"},
                          read_own("血气上限", 2 + scale))]
        listens = [listener("受到伤害后", "承受者", effects, **{"每场战斗最多触发": 2})]
    elif index == 9:
        counter = f"{realm_name}淤积"
        listens = [
            listener("造成伤害后", "来源",
                     [{"能力": "修改构筑计量", "目标": self_target(), "计量": counter,
                       "方式": "增加", "数值": 1, "最高值": 4 + scale}],
                     **{"每场战斗最多触发": 6}),
            listener("行动开始", "行动者",
                     [damage("暗伤发作", self_target(), read_own("血气上限", 2 + scale)),
                      {"能力": "修改构筑计量", "目标": self_target(), "计量": counter,
                       "方式": "清空"}],
                     条件=[{"能力": "数值条件",
                          "左值": {"能力": "读取数值", "来源": "构筑计量", "计量": counter,
                                   "目标": self_target()},
                          "比较": "大于等于", "右值": 3}],
                     **{"每次行动最多触发": 1}),
        ]
    elif index == 10:
        listens = [listener("技能施放后", "来源",
                            [{"能力": "修改技能冷却", "目标": self_target(),
                              "技能": {"能力": "选择技能", "范围": "可用技能",
                                       "排序": "冷却从低到高", "数量": 1},
                              "方式": "增加", "数值": 1}],
                            **{"每次行动最多触发": 1})]
    elif index == 11:
        listens = [listener("行动开始", "行动者",
                            [{"能力": "消耗资源", "目标": self_target(), "资源": "精神",
                              "数值": read_own("精神上限", 2 + scale),
                              "不足时是否失败": False}],
                            **{"每次行动最多触发": 1})]
    else:
        listens = [listener("技能施放失败后", "来源",
                            [status(f"{realm_name}余烬", actions=1, control=True)],
                            **{"每场战斗最多触发": 1})]
    return {
        "编号": f"62{realm_index:02d}{index:02d}",
        "名称": f"{realm_name}{word}",
        "来源类别": "境界自生",
        "境界": realm_id,
        "触发优先级": index,
        "触发": {"类型": "事件累计", "事件": spec["事件"], "角色": spec["角色"],
                 "次数": int(spec["次数"]) + scale},
        "战斗状态": {
            "类别": "负面",
            "剩余行动": 1 if index == 12 else 3,
            "持续单位": "状态承受者行动",
            "属性": {},
            "行动限制": [],
            "标签": ["长期伤势"],
            "监听": listens,
        },
        "叠加": {"层数上限": 3},
        "治疗": {"每层所需轮数": rounds_of(tier), "优先级": 30 + (realm_index - 1) * 12 + index},
        "说明": f"{realm_name}修士自身运转失衡后留下的{word}。\n",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--试运行", action="store_true", help="只报会改什么")
    args = parser.parse_args()

    injuries: list[dict] = json.loads(INJURY_FILE.read_text(encoding="utf-8"))
    realms: list[dict] = json.loads(REALM_FILE.read_text(encoding="utf-8"))
    rules: dict = json.loads(RULE_FILE.read_text(encoding="utf-8"))

    realms = sorted(realms, key=lambda item: str(item["编号"]))
    existing = {str(item["编号"]) for item in injuries}
    added: list[dict] = []
    patched = 0
    for realm_index, realm in enumerate(realms, start=1):
        realm_id = str(realm["编号"])
        realm_name = str(realm["名称"])
        tier = tier_of(realm_index)
        for index in sorted(DIRECTIONS):
            entry = new_entry(realm_index, realm_id, realm_name, index)
            if entry["编号"] in existing:
                continue
            added.append(entry)
        if tier > 1:
            target = next((item for item in injuries
                           if str(item.get("编号")) == f"62{realm_index:02d}06"), None)
            if target is not None:
                effects = sixth_effect(tier, realm_name)
                if effects is not None:
                    target["战斗状态"]["监听"][0]["效果"] = effects
                    patched += 1

    print(f"境界 {len(realms)} 个 · 每境界自生 {rules.get('每境界自生数量')} → {6 + len(DIRECTIONS)}")
    print(f"新增自生异状 {len(added)} 件")
    for entry in added[:3] + added[-2:]:
        print(f"   {entry['编号']} {entry['名称']} 触发={entry['触发']['事件']}×{entry['触发']['次数']} "
              f"轮数={entry['治疗']['每层所需轮数']}")
    print(f"第 6 种按层次改写 {patched} 件")
    if args.试运行:
        print("\n（试运行，未落盘）")
        return 0

    rules["每境界自生数量"] = 6 + len(DIRECTIONS)
    INJURY_FILE.write_text(
        json.dumps(injuries + added, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    RULE_FILE.write_text(
        json.dumps(rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n已写入 {INJURY_FILE.relative_to(ROOT)}（共 {len(injuries) + len(added)} 条）")
    print(f"已写入 {RULE_FILE.relative_to(ROOT)}（每境界自生数量 {rules['每境界自生数量']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
