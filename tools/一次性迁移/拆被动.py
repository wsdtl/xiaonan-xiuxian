"""把一个被动里混着的多条监听拆成「一个被动一条监听」，各给各的名字。

## 为什么

生成器把一张卡的被动写成**一个** `被动技能` 挂着 5~8 条 `监听事件`，正文里就是：

```
被动：
①[九转候敌]
每当其他己方施放技能后，…
每当其他己方击杀后，…
每当自身造成伤害后，…
每当自身造成伤害后，…
```

读起来像「一个被动里混了五件事」。负责人口径：**每个被动一个名字，都写上，不要混在一起**。

## 名字怎么起

沿用卡片自己的命名法（`卡名·短名`），给每一条监听起 `原短名（事件简称）`：

* 事件简称是**事件名的两字缩写**（`造成伤害后` → `伤后`、`技能施放后` → `技后`、
  `受到伤害后` → `承伤`……，见 `事件简称` 表，覆盖全部 66 个事件）；
* 同一段里事件重复时（`造成伤害后` 常有 2~3 条），再带上它自己的**词条后缀**
  （`伤后养元` / `伤后蓄元` / `伤后过杀`）——那条监听管的是哪个词条，就在名字里写清楚；
* 仍然重名才缀 `二` / `三`。

短名用**全角括号**接在后缀上而不是再写一个 `·`：正文只取最后一个 `·` 之后的部分
（`_short_name`），写成 `九转候敌·技后` 会被截成 `技后`。

## 别的形状

* `结算顺序` 拆完在卡内重新编号（1..N，保持原有先后）。
* 被动里若夹着非监听效果（实测没有），留在第一个拆出来的被动里。
* 真意 / 器律的构筑契约原本要求「能力数量 = 1」，拆完就是 N 项根能力——契约同步放宽为
  「最少能力 1、根能力只有被动技能」。

## 跑在哪一步

跑在 `重建数据与库.py` 的「重设计悬空引用」之后（那一步会往被动里补记录用的监听，
先拆会被它再拼回去）、「规范化」之前。幂等：重跑报「已是目标形态」。

用法：
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/拆被动.py           # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/拆被动.py --落盘
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import 构筑模板 as 模板  # noqa: E402

#: 事件 → 两字简称。**要覆盖全部事件**，漏一个就会退化成写全名（名字变长）。
事件简称: dict[str, str] = {
    "战场形成": "场成", "阵法展开": "阵展", "阵法轮转后": "阵轮", "阵法冲击后": "阵冲",
    "阵法崩解后": "阵崩", "地势承伤后": "地伤", "地势变化前": "地变前", "地势变化后": "地变",
    "战斗开始": "战始", "战斗结束": "战终", "战场规则变化后": "规变",
    "战斗对象入场后": "物入", "战斗对象退场后": "物退",
    "行动决策前": "策前", "行动决策后": "策后", "行动意图变化后": "意变",
    "行动开始": "行始", "行动跳过后": "行跳", "行动结束": "行终",
    "普通攻击前": "普攻前", "普通攻击后": "普攻", "追加攻击前": "追攻前", "追加攻击后": "追攻",
    "技能施放前": "技前", "技能施放后": "技后", "技能施放失败后": "技败",
    "使用丹药后": "丹后", "技能变化后": "技变", "技能冷却变化后": "冷变",
    "技能冷却完成后": "冷完", "命中判定前": "命判前", "命中后": "命中",
    "闪避后": "闪避", "暴击判定前": "暴判前", "暴击后": "暴击",
    "格挡判定前": "格判前", "格挡后": "格挡", "造成伤害前": "伤前", "造成伤害后": "伤后",
    "受到伤害后": "承伤", "护盾吸收后": "盾吸", "护盾破碎后": "盾碎",
    "恢复前": "复前", "恢复后": "复后", "获得护盾前": "盾得前", "获得护盾后": "盾得",
    "资源消耗前": "耗前", "资源消耗后": "耗后", "资源恢复前": "资复前", "资源恢复后": "资复",
    "资源变化后": "资变", "添加状态前": "附前", "添加状态后": "附后",
    "添加状态失败后": "附败", "状态层数变化后": "层变", "移除状态前": "移态前",
    "移除状态后": "移态", "状态反应后": "反应", "受到致命伤害": "濒死", "死亡后": "亡后",
    "击杀后": "击杀", "复活后": "复活", "形态切换后": "形变", "行动条变化后": "条变",
    "关联变化后": "契变", "事件转化后": "转事",
}


def 短名(全名: str) -> str:
    return str(全名 or "").rsplit("·", 1)[-1]


def 前缀(全名: str) -> str:
    文本 = str(全名 or "")
    return 文本.rsplit("·", 1)[0] if "·" in 文本 else ""


def 词条后缀(node: object) -> str:
    """这条监听管着的第一个词条（状态/计量/记录）的名字尾巴，用来区分同事件的多条。"""

    for 子 in 遍历(node):
        if isinstance(子, dict):
            状态 = 子.get("状态")
            名字 = 子.get("计量") or 子.get("名称")
            if not 名字 and isinstance(状态, dict):
                名字 = 状态.get("名称")
            if isinstance(名字, str) and len(名字) >= 2:
                return 名字[-2:]
    return ""


def 遍历(node: object):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from 遍历(v)
    elif isinstance(node, list):
        for v in node:
            yield from 遍历(v)


def 拆被动(实体: dict, 账: Counter, 报告: list[str]) -> int:
    能力 = 实体.get("能力")
    if not isinstance(能力, list):
        return 0
    新能力: list = []
    改动 = 0
    for 节点 in 能力:
        if not (isinstance(节点, dict) and 节点.get("能力") == "被动技能"):
            新能力.append(节点)
            continue
        效果 = [x for x in (节点.get("效果") or []) if isinstance(x, dict)]
        监听 = [x for x in 效果 if x.get("能力") == "监听事件"]
        其它 = [x for x in 效果 if x.get("能力") != "监听事件"]
        if len(监听) <= 1:
            新能力.append(节点)
            continue
        全名 = str(节点.get("名称") or "")
        原短名 = 短名(全名)
        卡前缀 = 前缀(全名)
        计数: Counter = Counter()
        拆出: list = []
        for 事件节点 in 监听:
            事件 = str(事件节点.get("事件") or "")
            基础 = 事件简称.get(事件, 事件)
            词条 = 词条后缀(事件节点)
            # 候选按「越具体越靠前」排：`承伤` → `承伤归元` → `承伤归元二` → `承伤二`…
            # 取第一个没被这张卡用过的。只往后缀上挂计数（不重算基础名）会撞车——实测
            # 同一事件同词条来四条时会撞名。
            候选们 = [基础]
            if 词条 and 词条 not in 基础:
                候选们.append(基础 + 词条)
                候选们.extend(f"{基础}{词条}{数字}" for 数字 in "二三四五六七八九")
            候选们.extend(f"{基础}{数字}" for 数字 in "二三四五六七八九")
            候选 = next(项 for 项 in 候选们 if not 计数[项])
            计数[候选] += 1
            后缀 = 候选
            新名 = f"{卡前缀}·{原短名}（{后缀}）" if 卡前缀 else f"{原短名}（{后缀}）"
            条目 = {k: v for k, v in 节点.items() if k not in ("效果", "名称")}
            条目["名称"] = 新名
            条目["效果"] = [事件节点] + (其它 if not 拆出 else [])
            拆出.append(条目)
        新能力.extend(拆出)
        改动 += len(拆出) - 1
        报告.append(
            f"{实体.get('编号')} {实体.get('名称')}：{原短名} 拆成 {len(拆出)} 个被动 —— "
            + "、".join(短名(x["名称"]) for x in 拆出)
        )
        账["拆出来的被动"] += len(拆出) - 1
    实体["能力"] = 新能力
    # 结算顺序在卡内重新编号（被动之间相对先后不变）
    序号 = 0
    for 节点 in 新能力:
        if isinstance(节点, dict) and 节点.get("能力") == "被动技能":
            序号 += 1
            if 节点.get("结算顺序") != 序号:
                节点["结算顺序"] = 序号
    账["被动总数"] += 序号
    return 改动


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--落盘", action="store_true", help="写回数据（默认为试算）")
    args = parser.parse_args()

    账: Counter = Counter()
    报告: list[str] = []
    总 = 0
    文件数 = 0
    for _面, 配置 in 模板.SEGMENTS.items():
        for path in sorted(配置["目录"].glob(配置["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            条目表 = 文档 if isinstance(文档, list) else [文档]
            改动 = sum(
                拆被动(e, 账, 报告) for e in 条目表 if isinstance(e, dict)
            )
            if not 改动:
                continue
            总 += 改动
            文件数 += 1
            if args.落盘:
                path.write_text(
                    json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )

    print(f"拆出被动 {总} 个，涉及 {文件数} 个文件")
    for 行 in 报告[:10]:
        print("  " + 行)
    if len(报告) > 10:
        print(f"  …… 其余 {len(报告) - 10} 张从略")
    for 键, 次 in 账.most_common():
        print(f"  {次:>5}  {键}")
    if not 总:
        print("已是目标形态（一个被动只挂一条监听），重跑无效果")
        return 0
    if not args.落盘:
        print("（试算，未落盘；加 --落盘 写入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
