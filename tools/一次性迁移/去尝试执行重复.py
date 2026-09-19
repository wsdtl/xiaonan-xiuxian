"""把「尝试执行」里与成功/失败分支**逐字相同**的那一步，从尝试效果里去掉。

## 为什么

生成器给「满条转锋」这类效果写成三份同一动作：

```jsonc
{"能力": "尝试执行",
 "尝试效果": [ …收益…, {"能力": "修改状态层数", "方式": "减少", "层数": 101, …}],
 "成功效果": [{"能力": "修改状态层数", "方式": "减少", "层数": 101, …}],
 "失败效果": [{"能力": "修改状态层数", "方式": "减少", "层数": 101, …}]}
```

成功时那一份会**再执行一遍**——同一个结算点上同一个动作出现两次，正是负责人早就定过的
硬规矩要根除的东西（`检查重复动作` 之前只看顺序执行，看不见这种跨分支的重复）。

两种重复的实际后果不一样：

* `修改构筑计量 / 清空`：幂等且不派发事件，去掉它行为不变（全库 1,650 处里的多数）；
* `修改状态层数 / 减少`：**每次都会派发一次 `状态层数变化后`**，于是监听多响一次；
  还有 `层数=13` / `11` 那几处是真扣两遍（层数上限 100，扣一次不清空）。

## 去掉哪一份

去**尝试效果里**那一份，而且只在它**也出现在 `成功效果` 里**时才去：

* 成功路径：`尝试效果` 跑完后再跑 `成功效果`（见 `mechanics._ability_attempt`，它**不回滚**），
  同一动作跑两遍；
* 失败路径：`尝试效果` 里那一步要么没跑到、要么已经失败，只有 `失败效果` 那一次生效——
  所以「只在失败效果里出现」不是重复，不能动。

这些重复项的 `不足时是否失败` 全是 `False`，去掉它也不会改变尝试的成败判定。

## 跑在哪一步

跑在 `重建数据与库.py` 的「清旧能力名」之后、「规范化」之前——规范化随后还能把因此
新挨到一起的重复顺手折掉；而**必须**在建库之前，库是从数据挖出来的，先改数据，
模板主体自然是改过的。

幂等：重跑报「去掉 0 步」。

用法：
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/去尝试执行重复.py           # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/去尝试执行重复.py --落盘
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
from game.core.combat.fold import flatten_sequences  # noqa: E402


def 指纹(node) -> str:
    return json.dumps(node, ensure_ascii=False, sort_keys=True)


def 去重节点(node: object, 账: Counter, 仅失败: Counter) -> int:
    改动 = 0
    if isinstance(node, dict):
        if node.get("能力") == "尝试执行":
            # `尝试效果` 在原文里常常是**一个 `顺序执行` 包着**（生成器的写法），
            # 拍到平才看得见它最后一个动作与成功分支重复——规范化与迁移本来也会拍平它。
            试 = flatten_sequences(node.get("尝试效果") or [])
            成功 = {指纹(项) for 项 in flatten_sequences(node.get("成功效果") or [])}
            失败 = {指纹(项) for 项 in flatten_sequences(node.get("失败效果") or [])}
            for 项 in 试:
                if 指纹(项) in 失败 and 指纹(项) not in 成功:
                    仅失败[指纹(项)[:60]] += 1
            保留 = [项 for 项 in 试 if 指纹(项) not in 成功]
            改动 += len(试) - len(保留)
            for 项 in 试:
                if 指纹(项) in 成功:
                    账[str(项.get("能力")) + "·" + str(项.get("方式") or "-")] += 1
            if 保留 != 试 or node.get("尝试效果") != 试:
                node["尝试效果"] = 保留
        for v in node.values():
            改动 += 去重节点(v, 账, 仅失败)
    elif isinstance(node, list):
        for v in node:
            改动 += 去重节点(v, 账, 仅失败)
    return 改动


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--落盘", action="store_true", help="写回数据（默认为试算）")
    args = parser.parse_args()

    账: Counter = Counter()
    仅失败: Counter = Counter()
    总 = 0
    文件数 = 0
    for _面, 配置 in 模板.SEGMENTS.items():
        for path in sorted(配置["目录"].glob(配置["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            条目表 = 文档 if isinstance(文档, list) else [文档]
            改动 = sum(去重节点(e, 账, 仅失败) for e in 条目表 if isinstance(e, dict))
            if not 改动:
                continue
            总 += 改动
            文件数 += 1
            if args.落盘:
                path.write_text(
                    json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )

    print(f"去掉重复步骤 {总} 处，涉及 {文件数} 个文件")
    for 形态, 次 in 账.most_common():
        print(f"  {次:>5}  {形态}")
    if 仅失败:
        print(f"注意：有 {sum(仅失败.values())} 处只出现在「失败效果」里（不是重复，没动）")
    if not 总:
        print("已无跨分支重复，重跑无效果")
        return 0
    if not args.落盘:
        print("（试算，未落盘；加 --落盘 写入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
