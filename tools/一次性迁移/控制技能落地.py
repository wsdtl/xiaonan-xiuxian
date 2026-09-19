"""控制技能落地：给主题相符的功法印一批「打向敌人」的控制技能（目标 ~50 个）。

审计出的偏斜：1161 个主动技能里，带「控制」标签的只有 6 个，而它们全是**打给自己**的
（`目标: 自身`、`行动限制: ["技能"]`，走火/反噬式），不是控制对手。控制标签因此几乎是空的
（强化 379 · 单体 295 · 疗愈 251 · 群体 185 · 守势 162 · 连击 82 · **控制 6**）。

本批在十个"本来就该有控制"的流派里印 50 个主动技能：咒法 · 禁术 · 符箓 · 音律 · 心经 ·
炼神秘术 · 阵图 · 毒经 · 御灵法 · 因果秘典（每门隔几张挑一张）。

控制状态的合法写法（照现有实例）：

    {"名称": …, "类别": "负面", "剩余行动": 1~2, "行动限制": ["技能"] 或 ["行动"],
     "是否控制": true, "控制基础命中率": 100}

`行动限制` 决定控法：`["技能"]` 是**禁技**，`["行动"]` 是**定身**。是否控制为真时，
目标的 `控制抵抗率` / `韧性` 会参与判定——这是引擎自带的反制，不用另写。

技能名带卡名前两字，保证全库唯一（`检查词条作用域.py` 的「技能」桶会查）。

    python tools/一次性迁移/控制技能落地.py --试运行
    python tools/一次性迁移/控制技能落地.py
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
GONGFA = ROOT / "data/战斗/内容/功法"
THEMES = ("咒法", "禁术", "符箓", "音律", "心经", "炼神秘术", "阵图", "毒经", "御灵法", "因果秘典")
#: 每门流派里隔几张加一个控制技能（20 张 / 4 = 5 个，十门共 50）。
STEP = 4
CONTROL_WORDS = ("滞魂", "禁言", "锁脉", "定身", "夺志", "封念")


def name_pool() -> set[str]:
    """全库已用的技能名与状态名。

    第一版拿卡名**前两字**做前缀，结果撞了——`玉清敕令咒` 与 `玉清静心心经` 前两字都是
    `玉清`，`太上斩念秘典` 与 `太上敕雷符经` 都是 `太上`，于是技能名与状态名双双重名
    （`检查词条作用域` 与 `test_term_naming` 各抓一次）。
    """

    def walk(node):
        if isinstance(node, dict):
            yield node
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)

    taken: set[str] = set()
    for path in ROOT.glob("data/**/*.json"):
        if "/定义/" in path.as_posix():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for node in walk(document):
            if node.get("能力") == "主动技能" and node.get("名称"):
                taken.add(str(node["名称"]))
            if node.get("能力") == "添加状态" and isinstance(node.get("状态"), dict):
                if node["状态"].get("名称"):
                    taken.add(str(node["状态"]["名称"]))
    return taken


def free_name(base: str, taken: set[str]) -> str:
    for suffix in ("", "纹", "印", "痕", "兆", "契", "符", "诀", "令"):
        if base + suffix not in taken:
            taken.add(base + suffix)
            return base + suffix
    raise SystemExit(f"名字用尽：{base}")


def lock(kind: str) -> list[str]:
    return ["技能"] if kind == "禁技" else ["行动"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--试运行", action="store_true")
    args = parser.parse_args()

    added = 0
    rows: list[str] = []
    taken = name_pool()
    for path in sorted(GONGFA.glob("功法-*.json")):
        theme = path.stem.split("-")[1]
        if theme not in THEMES:
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        for index, card in enumerate(document):
            if index % STEP:
                continue
            abilities = card.get("能力") or []
            skills = [node for node in abilities if node.get("能力") == "主动技能"]
            if not skills:
                continue
            word = CONTROL_WORDS[(index // STEP) % len(CONTROL_WORDS)]
            kind = "定身" if word in {"定身", "锁脉"} else "禁技"
            order = max(int(node.get("释放顺序") or 1) for node in skills) + 1
            name = free_name(f"{str(card['名称'])[:2]}{word}", taken)
            node = {
                "能力": "主动技能",
                "名称": name,
                "释放顺序": order,
                "精神消耗": 16,
                "冷却行动": 4,
                # 效果列表里**不能放裸的 `选择目标`**：它是「目标类」能力，没有执行器，
                # 放进去真实对局会抛 `ValueError: 战斗核心未实现执行器：选择目标`。
                # 效果自己带 `目标` 字段就够了。
                "效果": [
                    {"能力": "添加状态",
                     "目标": {"能力": "选择目标", "范围": "当前目标"},
                     "状态": {"名称": free_name(f"{name}印", taken), "类别": "负面",
                              "剩余行动": 1 if kind == "定身" else 2,
                              "持续单位": "状态承受者行动",
                              "行动限制": lock(kind), "属性": {},
                              "标签": ["控制"],
                              "是否控制": True, "控制基础命中率": 100}},
                ],
            }
            abilities.append(node)
            added += 1
            rows.append(f"  {card['编号']} {card['名称']:<6}({theme}) +{name}（{kind}）")
        if not args.试运行:
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")

    print(f"新增控制技能 {added} 个")
    for line in rows[:6]:
        print(line)
    if len(rows) > 6:
        print(f"  …… 其余 {len(rows) - 6} 个")
    if args.试运行:
        print("\n（试运行，未落盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
