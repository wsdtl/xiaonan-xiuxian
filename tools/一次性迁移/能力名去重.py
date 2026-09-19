"""能力名全局去重：主动 / 被动的**短名**在全库只许有一个。

## 为什么

正文里显示的是短名（`卡名·短名` 取 `·` 之后那段）。同一个短名落在两张卡上，
玩家在两张卡里看到同一个技能名、战报里也分不出是哪张卡的——负责人要求
**每个名字全局不一样**，而且「符合环境就行」，不需要另起新词。

## 怎么改

撞名的，给它的短名**补上这张卡自己的词条前缀**——那正是这套命名的原生写法
（`九转系丹大道篇` 的技能叫 `九转系象` / `九转候敌`，`龙虎大丹丹经` 的叫 `龙虎同苏`）。
前缀从这张卡**自己造的词条**里取（`添加状态` / `修改状态层数` 的状态名、`修改构筑计量`
的计量名、`记录战斗事实` 的事实名），取它们的最长公共前缀（≥2 字才算）。

* 撞名组里优先改**短名没带自己前缀**的那一个（另一个通常本来就带着自己的前缀，
  比如真意卡整张卡就叫那个名字）；
* 补完还撞（两张卡前缀相同）才缀 `二` / `三`；
* 同一张卡内部重复也一并处理（先自己前缀、再缀号）。

只改 `名称` 字段，`编号`、效果树、词条一概不动；技能不被别处按名字引用（`选择技能`
按范围/排序选），所以改名不影响结算。

## 跑在哪一步

跑在 `重建数据与库.py` 的「拆被动」之后（拆分会产生新的 `（事件简称）` 名字）、
「规范化」之前。幂等：重跑报「已无撞名」。

用法：
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/能力名去重.py           # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/能力名去重.py --落盘
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import 构筑模板 as 模板  # noqa: E402

#: 词条来源：这些字段里的名字是这张卡**自己造**的，带它的词条前缀。
词条键 = ("计量",)
词条状态键 = ("添加状态", "修改状态层数", "移除状态前", "移除状态后", "状态条件")


def 短名(全名: str) -> str:
    return str(全名 or "").rsplit("·", 1)[-1]


def 前缀段(全名: str) -> str:
    文本 = str(全名 or "")
    return 文本.rsplit("·", 1)[0] + "·" if "·" in 文本 else ""


def 词条前缀(实体: dict) -> str:
    """这张卡的「身份词」：**卡名与它自己造的词条名的最长公共前缀**。

    生成器的词条名就是 `<身份词><后缀>`（`雁回引诀` / `雁回养元`…），所以拿卡名一起去求
    公共前缀，得到的就是那个两字上下的身份词（`雁回`）。只用词条之间求公共前缀会求得
    太长——只有一件词条时公共前缀就是整条词条名，改名会变成
    `雁回引诀旧痛复响` 这种笨名字（实测踩过）。
    """

    名们: list[str] = [str(实体.get("名称") or "")]

    def 走(node):
        if isinstance(node, dict):
            if node.get("能力") == "修改构筑计量" and isinstance(node.get("计量"), str):
                名们.append(str(node["计量"]))
            if node.get("能力") in ("添加状态", "修改状态层数", "状态条件"):
                状态 = node.get("状态")
                if isinstance(状态, dict) and isinstance(状态.get("名称"), str):
                    名们.append(str(状态["名称"]))
            if node.get("能力") == "记录战斗事实" and isinstance(node.get("名称"), str):
                名们.append(str(node["名称"]))
            for v in node.values():
                走(v)
        elif isinstance(node, list):
            for v in node:
                走(v)

    走(实体)
    名们 = [名 for 名 in 名们 if len(名) >= 2]
    公共 = ""
    if len(名们) >= 2:
        最短 = min(len(名) for 名 in 名们)
        for i in range(最短):
            字 = {名[i] for 名 in 名们}
            if len(字) != 1:
                break
            公共 += 字.pop()
    if len(公共) >= 2:
        return 公共
    # 求不出公共前缀（词条不带卡名前缀，或者这张卡没有自造词条）：退一步用**卡名的前两字**
    # 当身份词，反正「符合环境就行」——总比 `留魂（亡后）二` 这种缀号名字好读。
    卡名 = str(实体.get("名称") or "")
    return 卡名[:2] if len(卡名) >= 2 else ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--落盘", action="store_true", help="写回数据（默认为试算）")
    args = parser.parse_args()

    数字们 = "二三四五六七八九"

    # 第一遍：把全库能力（含它所在的文档与实体）收起来，按短名分组。
    条目表: list[tuple[pathlib.Path, object, dict, dict]] = []
    分组: dict[str, list[int]] = collections.defaultdict(list)
    for _面, 配置 in 模板.SEGMENTS.items():
        for path in sorted(配置["目录"].glob(配置["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            实体们 = 文档 if isinstance(文档, list) else [文档]
            for 实体 in 实体们:
                if not isinstance(实体, dict) or not 实体.get("编号"):
                    continue
                前缀 = 词条前缀(实体)
                for 节点 in 实体.get("能力") or ():
                    if isinstance(节点, dict) and 节点.get("能力") in ("主动技能", "被动技能"):
                        分组[短名(节点.get("名称"))].append(len(条目表))
                        条目表.append((path, 文档, 实体, {"节点": 节点, "前缀": 前缀}))

    已决定: dict[int, str] = {}
    for 短, 序号们 in 分组.items():
        if len(序号们) == 1:
            continue
        # 谁保留原名：优先「短名本来就带着自己词条前缀」的那个（真意卡常整张卡就叫这个名字）；
        # 其余按文件顺序改。
        保留 = next(
            (i for i in 序号们 if 条目表[i][3]["前缀"] and 短.startswith(条目表[i][3]["前缀"])),
            序号们[0],
        )
        已用 = {短}
        for i in 序号们:
            if i == 保留:
                continue
            前缀 = 条目表[i][3]["前缀"]
            候选们 = []
            if 前缀 and not 短.startswith(前缀):
                候选们.append(f"{前缀}{短}")
            候选们.extend(f"{短}{数字}" for 数字 in 数字们)
            if 前缀:
                候选们.extend(f"{前缀}{短}{数字}" for 数字 in 数字们)
            候选 = next((项 for 项 in 候选们 if 项 not in 已用), None)
            if 候选 is None:
                continue
            已用.add(候选)
            已决定[i] = 候选

    改动: list[str] = []
    脏文档: dict[pathlib.Path, object] = {}
    for i, (path, 文档, 实体, 信息) in enumerate(条目表):
        新短 = 已决定.get(i)
        if not 新短:
            continue
        原名 = str(信息["节点"].get("名称") or "")
        信息["节点"]["名称"] = f"{前缀段(原名)}{新短}"
        改动.append(f"{实体.get('编号')} {实体.get('名称')}：{短名(原名)} → {新短}")
        脏文档[path] = 文档

    if args.落盘:
        for path, 文档 in 脏文档.items():
            path.write_text(
                json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

    print(f"改名 {len(改动)} 处")
    for 行 in 改动[:25]:
        print("  " + 行)
    if len(改动) > 25:
        print(f"  …… 其余 {len(改动) - 25} 处从略")
    if not 改动:
        print("已无撞名，重跑无效果")
        return 0
    if not args.落盘:
        print("（试算，未落盘；加 --落盘 写入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
