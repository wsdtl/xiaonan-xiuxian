"""重设计「读了却从来没人积累」的引用：把永远不生效的效果变成会生效的。

## 病

生成器给一部分卡配了「攒够 N 就放一次」的收尾效果，但**没有配积累点**——读的那一半在、
写的那一半不在，条件永远不成立，收尾效果一次也不触发。实测 40 张卡（功法 38 · 真意 2）。

查过历史：机制库时代它就是 `601127 连锁传导`，机制本体也只有「读 + 清空」，
所以这不是迁移弄坏的，是从生成器起就缺写点。负责人口径：**重新设计**，而且
「计量本来就太多」——所以不要另加积累点，把这些死计量直接拿掉、让效果照常生效。

## 两类，两种改法

**① 构筑计量族（28 张）**——把死计量删掉，收尾效果改成无条件：

```jsonc
{"能力": "条件执行", "条件": [{"左值": {"读取数值", "计量": "九转裂锋"}, "比较": "大于等于", "右值": 4}],
 "成立效果": [{"造成伤害", "数值": {"读取数值", "计量": "九转裂锋", "百分比": 30}}, {"修改构筑计量", "计量": "九转裂锋", "方式": "清空"}]}
```
→
```jsonc
{"造成伤害", "数值": {"读取数值", "来源": "自身属性", "属性": "攻击", "百分比": 30}}
```

* 拆掉 `条件执行` 外壳（它的条件永远不成立，成立效果从没跑过；没有不成立分支），
  成立效果直接接进原来的位置；
* 用死计量当**数值**的读取（`百分比=P`）改成读自身的攻击 `×P%`——同一个百分比，
  换一个有意义的单位；
* 死计量的 `清空` 与其余读取一并删掉，计量条数随之少一条。

**② 战斗记录族（12 张）**——补上现成写法的记录节点（不减内容，只把它该记的记上）：

| 事实 | 现成写法（照抄库里已有的卡） |
| --- | --- |
| `敌行兆` | `行动决策后` → 记录 `值=1 方式=覆盖 保留数量=1` |
| `镜伤` | `受到伤害后` → 记录 `值=本次数值 方式=覆盖 保留数量=1` |
| `待偿伤` | `受到伤害后` → 记录 `值=本次数值 方式=累加 保留数量=12` |
| `伤势账` | `受到伤害后` → 记录 `值=本次数值 方式=累加 保留数量=20` |

监听挂在卡自己的**被动技能**槽位里（`挪监听入被动.py` 那条教训：监听属于常驻能力）。

## 跑在哪一步

跑在 `重建数据与库.py` 的「去尝试执行重复」之后、「规范化」之前——规范化随后会把
因此新挨到一起的重复顺手折掉；而且必须**在建库之前**，库是从数据挖出来的。

幂等：重跑报「未发现悬空引用」。

用法：
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/重设计悬空引用.py            # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/重设计悬空引用.py --落盘
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import 构筑模板 as 模板  # noqa: E402

#: 战斗记录的现成写法。`(事件, 观察角色, 阵营关系, 记录节点, 每次行动最多触发)`。
事实写法: dict[str, tuple] = {
    "敌行兆": (
        "行动决策后", "来源", "任意敌方",
        {"能力": "记录战斗事实",
         "归属": {"能力": "选择目标", "范围": "自身"},
         "名称": "敌行兆", "值": 1, "方式": "覆盖", "保留数量": 1},
        1,
    ),
    "镜伤": (
        "受到伤害后", "承受者", "自身",
        {"能力": "记录战斗事实",
         "归属": {"能力": "选择目标", "范围": "自身"},
         "名称": "镜伤",
         "值": {"能力": "读取数值", "来源": "本次数值"},
         "方式": "覆盖", "保留数量": 1},
        3,
    ),
    "待偿伤": (
        "受到伤害后", "承受者", "自身",
        {"能力": "记录战斗事实",
         "归属": {"能力": "选择目标", "范围": "自身"},
         "名称": "待偿伤",
         "值": {"能力": "读取数值", "来源": "本次数值"},
         "方式": "累加", "保留数量": 12},
        3,
    ),
    "伤势账": (
        "受到伤害后", "承受者", "自身",
        {"能力": "记录战斗事实",
         "归属": {"能力": "选择目标", "范围": "自身"},
         "名称": "伤势账",
         "值": {"能力": "读取数值", "来源": "本次数值"},
         "方式": "累加", "保留数量": 20},
        3,
    ),
}

序列键 = ("效果", "尝试效果", "成功效果", "失败效果", "成立效果", "不成立效果", "选项")


def 引用名(node: object) -> tuple[str, str] | None:
    """这个读取节点读的是谁：`(来源, 名字)`。"""

    if not isinstance(node, dict) or node.get("能力") != "读取数值":
        return None
    来源 = str(node.get("来源") or "")
    名字 = node.get("状态") or node.get("计量") or node.get("名称") or ""
    if 来源 in ("状态层数", "构筑计量", "战斗记录") and isinstance(名字, str) and 名字:
        return 来源, 名字
    return None


def 读的(node: dict, 名字: str, 来源: str) -> bool:
    return node.get("能力") == "读取数值" and str(node.get(来源字段[来源]) or "") == 名字


来源字段 = {"状态层数": "状态", "构筑计量": "计量", "战斗记录": "名称"}


def 扫引用(卡) -> tuple[dict[tuple[str, str], int], set[str]]:
    读: Counter = Counter()
    写: set[str] = set()

    def 走(node):
        if isinstance(node, dict):
            对 = 引用名(node)
            if 对:
                读[对] += 1
            能力 = node.get("能力")
            if 能力 in ("修改构筑计量", "修改状态层数", "添加状态", "记录战斗事实"):
                名字 = (
                    node.get("计量") or node.get("名称")
                    or (node.get("状态") or {}).get("名称") or ""
                )
                方式 = str(node.get("方式") or "")
                if isinstance(名字, str) and 名字 and (
                    能力 != "修改构筑计量" or 方式 in ("增加", "设置")
                ):
                    写.add(名字)
            for v in node.values():
                走(v)
        elif isinstance(node, list):
            for v in node:
                走(v)

    走(卡)
    return dict(读), 写


def 改为攻击(node: object, 死名: str) -> None:
    """把「读这个死计量」的数值改成「读自身攻击」，百分比照旧。

    只动这个死计量：活着的计量（比如同卡的 `××归元`）的伤害读数一律不碰。
    """

    for 子 in 遍历(node):
        if (
            isinstance(子, dict)
            and 子.get("能力") == "读取数值"
            and str(子.get("计量") or "") == 死名
            and isinstance(子.get("百分比"), (int, float))
        ):
            子.pop("计量", None)
            # `最高值` / `最低值` 原本是**那个计量**的读数护栏（读计数时封顶），
            # 换成「自身攻击×P%」之后它们没有意义——留着正文会写成「攻击×30%（最高100）」。
            子.pop("最高值", None)
            子.pop("最低值", None)
            子["来源"] = "自身属性"
            子["属性"] = "攻击"


def 遍历(node: object):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from 遍历(v)
    elif isinstance(node, list):
        for v in node:
            yield from 遍历(v)


def 删死计量(node: object, 名字: str) -> int:
    """删掉死计量剩下的一切读写节点，返回删除数。"""

    删 = 0
    if isinstance(node, dict):
        for key in list(node):
            if key in 序列键 and isinstance(node[key], list):
                保留 = [x for x in node[key] if not _是死节点(x, 名字)]
                删 += len(node[key]) - len(保留)
                node[key] = 保留
                if not 保留:
                    node.pop(key, None)
                else:
                    for x in 保留:
                        删 += 删死计量(x, 名字)
            elif isinstance(node[key], (dict, list)):
                删 += 删死计量(node[key], 名字)
    elif isinstance(node, list):
        for x in node:
            删 += 删死计量(x, 名字)
    return 删


def _是死节点(node: object, 名字: str) -> bool:
    if not isinstance(node, dict):
        return False
    if node.get("能力") == "修改构筑计量" and str(node.get("计量") or "") == 名字:
        return True
    return node.get("能力") == "读取数值" and str(node.get("计量") or "") == 名字


def 拆条件外壳(node: object, 死名: str, 账: Counter) -> object:
    """把「若死计量 ≥N 则…」的外壳拆掉，成立效果直接接进原位。"""

    if isinstance(node, list):
        出: list = []
        for 项 in node:
            新 = 拆条件外壳(项, 死名, 账)
            if isinstance(新, list):
                出.extend(新)
            else:
                出.append(新)
        return 出
    if not isinstance(node, dict):
        return node
    # 监听的 `条件` 直接挂在监听节点上（不是 `条件执行`）：把读死计量的那条条件去掉，
    # 监听就按它该有的时点生效（例：`行动决策前` 取消敌方行动意图、每场一次）。
    if node.get("能力") == "监听事件" and isinstance(node.get("条件"), list):
        保留 = [条 for 条 in node["条件"] if not _条件读死(条, 死名)]
        if len(保留) != len(node["条件"]):
            账["去掉监听上的死条件"] += 1
            if 保留:
                node["条件"] = 保留
            else:
                node.pop("条件", None)
    for key in list(node):
        if key in 序列键 and isinstance(node[key], list):
            node[key] = 拆条件外壳(node[key], 死名, 账)
        elif isinstance(node[key], (dict, list)):
            node[key] = 拆条件外壳(node[key], 死名, 账)
    if node.get("能力") != "条件执行":
        return node
    条件 = node.get("条件") or []
    if not 条件 or not all(
        isinstance(条, dict) and _条件读死(条, 死名) for 条 in 条件
    ):
        return node
    if node.get("不成立效果"):
        账["有不成立分支（跳过，待人工看）"] += 1
        return node
    成立 = node.get("成立效果") or []
    改为攻击(成立, 死名)
    账["拆掉条件外壳"] += 1
    return 成立


def _条件读死(条: dict, 死名: str) -> bool:
    if 条.get("能力") != "数值条件":
        return False
    左 = 条.get("左值")
    return bool(左) and any(
        isinstance(x, dict)
        and x.get("能力") == "读取数值"
        and str(x.get("计量") or "") == 死名
        for x in 遍历(左)
    )


def 挂记录(卡: dict, 事实: str) -> bool:
    """把缺的记录节点挂进这张卡的被动槽位；没有被动槽位就返回 False。"""

    事件, 角色, 关系, 记录, 上限 = 事实写法[事实]
    监听 = {
        "能力": "监听事件",
        "事件": 事件,
        "观察角色": 角色,
        "阵营关系": 关系,
        "效果": [copy.deepcopy(记录)],
        "每次行动最多触发": 上限,
    }
    for 能力 in 卡.get("能力") or ():
        if isinstance(能力, dict) and 能力.get("能力") == "被动技能":
            (能力.setdefault("效果", [])).append(监听)
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--落盘", action="store_true", help="写回数据（默认为试算）")
    args = parser.parse_args()

    账: Counter = Counter()
    报告: list[str] = []
    for _面, 配置 in 模板.SEGMENTS.items():
        for path in sorted(配置["目录"].glob(配置["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            条目表 = 文档 if isinstance(文档, list) else [文档]
            改动 = 0
            for 实体 in 条目表:
                if not isinstance(实体, dict):
                    continue
                读, 写 = 扫引用(实体)
                漏 = [对 for 对 in 读 if 对[1] not in 写]
                if not 漏:
                    continue
                卡 = f"{path.name} {实体.get('编号')} {实体.get('名称')}"
                for 来源, 名字 in sorted(漏):
                    if 来源 == "构筑计量":
                        拆条件外壳(实体, 名字, 账)
                        改为攻击(实体, 名字)
                        删死计量(实体, 名字)
                        账["拆掉的死计量"] += 1
                        报告.append(f"{卡}：拆掉死计量 {名字}（收尾效果改为无条件）")
                        改动 += 1
                    elif 来源 == "战斗记录" and 名字 in 事实写法:
                        if 挂记录(实体, 名字):
                            账["补上的记录"] += 1
                            报告.append(f"{卡}：补上 {名字} 的记录节点")
                            改动 += 1
                        else:
                            账["没有被动槽位（未处理）"] += 1
                            报告.append(f"{卡}：{名字} 无处挂（没有被动技能槽位）")
                    else:
                        账[f"未覆盖：{来源}"] += 1
                        报告.append(f"{卡}：{来源}·{名字} 没有现成写法，未动")
            if 改动 and args.落盘:
                path.write_text(
                    json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )

    报告有 = [x for x in 报告 if "改为无条件" in x or "补上" in x]
    print(f"重设计 {len(报告有)} 处")
    for 行 in 报告:
        print("  " + 行)
    for 键, 次 in 账.most_common():
        print(f"  {次:>4}  {键}")
    if not 报告:
        print("未发现悬空引用，重跑无效果")
        return 0
    if not args.落盘:
        print("（试算，未落盘；加 --落盘 写入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
