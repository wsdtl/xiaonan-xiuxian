"""冷机制落地：把用得最少（或完全没用过）的原子能力用到贴题的地方。

机制覆盖审计（66 个原子能力）：

    完全没用过  随机数值（0 次）
    极少        组合条件 3 · 缩短状态 5 · 转移伤害 14 · 聚合数值 15 · 状态条件 18 · …

负责人定的方向是"每个机制尽量要平均、没有的机制可以考虑使用上"，所以本工具只挑
**主题上最贴**的落点，不硬塞：

| 机制 | 落点 | 理由 |
| --- | --- | --- |
| `随机数值` | 天机 / 劫丹 | 天机难测、劫数无常：回一口是多是少，掷出来才知道 |
| `缩短状态` | 克制 / 控制 | 反制与禁制：把对方身上挂着的增益缩短 |
| `组合条件` | 劫丹 / 绝境 | 双门槛才发作：既到濒死线、又确实挨了这一下 |

用法：

    python tools/一次性迁移/冷机制落地.py --试运行
    python tools/一次性迁移/冷机制落地.py
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PILLS = ROOT / "data/物品/炼丹/内容/丹药/战丹"


def self_target() -> dict:
    return {"能力": "选择目标", "范围": "自身"}


def own(attribute: str, percent: int) -> dict:
    return {"能力": "读取数值", "来源": "自身属性", "属性": attribute,
            "百分比": percent, "最低值": 1}


def random_gain(low: int, high: int, resource: str = "血气") -> dict:
    """`随机数值`：同一枚丹每次回的量不同。"""

    return {"能力": "恢复资源", "目标": self_target(), "资源": resource,
            "数值": {"能力": "随机数值", "最低值": low, "最高值": high, "取整": True}}


def shorten_enemy_buff(amount: int) -> dict:
    """`缩短状态`：把当前目标身上的正面状态缩短。"""

    return {"能力": "缩短状态",
            "状态": {"能力": "选择状态",
                     "目标": {"能力": "选择目标", "范围": "当前目标"},
                     "分类": "正面", "排序": "剩余行动从多到少"},
            "持续数值": amount, "方式": "减少"}


def blood_below(percent: int) -> dict:
    """"血气剩不到 percent%" —— 写成"已损失 ≥ (100-percent)% 上限"。

    注意别拿 `自身属性/血气上限` 当当前血量（那样两边都是上限，条件恒不成立、
    这枚丹会变成哑弹）：当前血量只有 `自身当前血气` / `自身已损失血气` 读得到。
    """

    return {"能力": "数值条件",
            "左值": {"能力": "读取数值", "来源": "自身已损失血气"},
            "比较": "大于等于",
            "右值": {"能力": "读取数值", "来源": "自身属性", "属性": "血气上限",
                     "百分比": 100 - percent}}


def hit_landed() -> dict:
    return {"能力": "数值条件", "左值": {"能力": "读取数值", "来源": "本次数值"},
            "比较": "大于", "右值": 0}


#: 落点表：编号 → (机制, 参数)。只挂一条，挂在它第一条监听的效果末尾；
#: `组合条件` 挂在监听节点的 `条件` 上，管的是"这一下响不响"。
TARGETS: dict[str, tuple[str, tuple]] = {
    # 天机 · 劫丹：回一口是多是少，掷出来才知道
    "120153": ("随机", (6, 18, "血气")),
    "120155": ("随机", (5, 15, "精神")),
    "120158": ("随机", (8, 24, "血气")),
    "120159": ("随机", (10, 26, "护盾")),
    "120147": ("随机", (4, 20, "血气")),
    "120152": ("随机", (6, 22, "血气")),
    # 克制 · 控制：反制与禁制
    "120121": ("缩短", (2,)),
    "120126": ("缩短", (1,)),
    "120127": ("缩短", (2,)),
    "120128": ("缩短", (3,)),
    "120055": ("缩短", (1,)),
    "120058": ("缩短", (2,)),
    # 劫丹 · 绝境：双门槛
    "120145": ("组合", ()),
    "120146": ("组合", ()),
    "120034": ("组合", ()),
    "120038": ("组合", ()),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--试运行", action="store_true")
    args = parser.parse_args()

    files = sorted(PILLS.glob("*.json"))
    documents = {path: json.loads(path.read_text(encoding="utf-8")) for path in files}
    index = {str(entry["编号"]): (path, entry) for path, document in documents.items()
             for entry in document}

    touched: list[str] = []
    for pill_id, (kind, params) in TARGETS.items():
        found = index.get(pill_id)
        if found is None:
            print(f"  跳过 {pill_id}：找不到")
            continue
        path, entry = found
        payload = entry.get("使用效果") or {}
        listeners = payload.get("监听") or []
        if not listeners:
            print(f"  跳过 {pill_id} {entry['名称']}：没有监听")
            continue
        if kind == "随机":
            listeners[0]["效果"].append(random_gain(*params))
            touched.append(f"  {pill_id} {entry['名称']:<7}({path.stem[3:]}) 补 随机数值 "
                           f"{params[0]}~{params[1]} {params[2]}")
        elif kind == "缩短":
            listeners[0]["效果"].append(shorten_enemy_buff(*params))
            touched.append(f"  {pill_id} {entry['名称']:<7}({path.stem[3:]}) 补 缩短状态 "
                           f"{params[0]} 行动")
        else:
            listeners[0]["条件"] = [{"能力": "组合条件", "关系": "全部成立",
                                   "条件": [blood_below(60), hit_landed()]}]
            touched.append(f"  {pill_id} {entry['名称']:<7}({path.stem[3:]}) 加 组合条件"
                           f"（血气 ≤60% 且本次数值 >0）")

    print(f"落点 {len(touched)} 枚")
    for line in touched:
        print(line)
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
