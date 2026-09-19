"""悬空引用判据：一张卡读了某个状态层数 / 构筑计量 / 战斗记录，却没有一处把它建起来。

读到的永远是 0，条件永远不成立，那段效果一次也不会触发——「设计里写了、实际不存在」。
第 71 轮清掉 44 处（死计量拆掉收尾外壳、事实补记录节点），这条判据留着防止再长出来。

判据口径：

* **按卡判**。构筑是各卡自带的完整能力树，同一张卡读的东西必须由它自己建立；跨卡引用
  （另一张功法写的记录）不在构建里成立，所以不算合法来源。
* 写点算三种：`添加状态`（状态）、`修改构筑计量 方式=增加/设置`、`记录战斗事实`。
  `清空` 不算写点——它正是「只清不积」的那一半。
* 只报**字面名字**。名字写成参数占位符时无法在单卡内判定，跳过。

**退出码：0 = 没有悬空引用，1 = 有。**
"""

from __future__ import annotations

import collections
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from 全库扫描 import 全库文档  # noqa: E402

来源字段 = {"状态层数": "状态", "构筑计量": "计量", "战斗记录": "名称"}


def 扫(卡) -> tuple[dict[tuple[str, str], int], set[str]]:
    读: collections.Counter = collections.Counter()
    写: set[str] = set()

    def 走(node):
        if isinstance(node, dict):
            if node.get("能力") == "读取数值":
                来源 = str(node.get("来源") or "")
                名字 = node.get(来源字段.get(来源, "")) or ""
                if 来源 in 来源字段 and isinstance(名字, str) and 名字:
                    读[(来源, 名字)] += 1
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
            for value in node.values():
                走(value)
        elif isinstance(node, list):
            for value in node:
                走(value)

    走(卡)
    return dict(读), 写


def main() -> int:
    实体数 = 0
    悬空: list[tuple[str, str, str, int]] = []
    for 相对, 文档 in 全库文档():
        条目 = 文档 if isinstance(文档, list) else [文档]
        for 实体 in 条目:
            if not isinstance(实体, dict) or not 实体.get("编号"):
                continue
            实体数 += 1
            读, 写 = 扫(实体)
            for (来源, 名字), 次 in sorted(读.items()):
                if 名字 not in 写:
                    悬空.append((相对, str(实体.get("编号")), f"{来源}·{名字}", 次))

    print(f"实体 {实体数} 个")
    print(f"悬空引用 {len(悬空)} 处")
    for 相对, 编号, 名字, 次 in 悬空[:30]:
        print(f"    {相对} {编号} 读 {名字}（{次} 处）")
    return 1 if 悬空 else 0


if __name__ == "__main__":
    raise SystemExit(main())
