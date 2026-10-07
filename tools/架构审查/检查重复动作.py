"""全量核对「同一动作不得写两遍」这条硬规则，以及其他渲染底线。

口径：

1. `未支持` / `None` 泄漏 —— 渲染器还有没有没接上的原子能力；
2. **结构层重复** —— 展开后的数据里，同一个效果数组有没有两个一字不差、
   或「同一计量/层数两笔增量」的相邻动作（这是硬规则，必须为 0）；
3. **渲染层重复** —— 正文里有没有相邻两行完全一样（读起来就是写重了）。

第 2 条是关键：它直接对着**可执行结构**判，不依赖渲染措辞。
"""

from __future__ import annotations

import pathlib as _pathlib
import sys as _sys

# 共用库住在 tools/库/：脚本按文件运行时 sys.path[0] 是自己的目录，得手动加。
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1] / "库"))

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from 构筑模板展开 import load_build_json  # noqa: E402
from game.core.combat.card_text import render_body, render_listeners  # noqa: E402
from 规则层 import load_rule_layer  # noqa: E402
from game.core.combat.fold import flatten_sequences  # noqa: E402

SEGMENTS = (
    ("功法", ROOT / "data/战斗/内容/功法", "功法-*.json"),
    ("真意", ROOT / "data/战斗/内容/真意", "真意-*.json"),
    ("器律", ROOT / "data/物品/炼器/内容", "器律*.json"),
    ("战场环境", ROOT / "data/战斗/内容/战场环境", "*.json"),
    ("伤势", ROOT / "data/角色/内容", "伤势.json"),
    ("战丹", ROOT / "data/物品/炼丹/内容/丹药/战丹", "*.json"),
)

SEQUENCE_KEYS = ("效果", "尝试效果", "成功效果", "失败效果", "成立效果", "不成立效果", "选项")
INCREMENTS = ("修改构筑计量", "修改状态层数")
SINGLE = ("遍历目标", "遍历", "恢复资源")


def 增量键(node: dict):
    """「同一笔账」的判等键：目标 + 计量/状态。**不带方向、不带上限**。

    方向不带：`+2` 与 `-2` 是同一个账上的两笔，合起来才是净结果。
    上限不带：上限不同只说明两笔的封顶写法不一致。
    """

    ability = node.get("能力")
    if ability not in INCREMENTS:
        return None
    if ability == "修改构筑计量":
        return (ability,
                json.dumps(node.get("目标"), sort_keys=True, ensure_ascii=False),
                json.dumps(node.get("计量"), ensure_ascii=False))
    return (ability, json.dumps(node.get("状态"), sort_keys=True, ensure_ascii=False))


def 检查序列(序列: list, path: str, out: list) -> None:
    """同一结算点内：同计量的增量只能有一条；一字不差的重复项只能有一条。

    **不要求相邻**。同一个结算点上同一笔账的两笔加法，中间隔着「建立关联」「记录
    事实」这类动作也仍然是同一个动作的两半（实测漏过 143 处计量 + 143 处层数）。
    只查相邻的版本查不出这些。
    """

    已见: dict[tuple, int] = {}
    for 序, item in enumerate(序列):
        if not isinstance(item, dict):
            continue
        键 = 增量键(item) if isinstance(item.get("能力"), str) else None
        if 键 is not None:
            if 键 in 已见:
                out.append(("同一结算点两笔同计量增量", f"{path}[{序}]/{item['能力']}",
                            序列[已见[键]], item))
                continue
            已见[键] = 序
            continue
        # 一字不差的重复项：`SINGLE` 类动作，或模板引用写两遍。
        for 前 in range(序 - 1, max(-1, 序 - 4), -1):
            if 序列[前] == item:
                能力 = item.get("能力")
                if (isinstance(能力, str) and 能力 in SINGLE) or "模板" in item:
                    out.append(("一字不差的重复动作", f"{path}[{序}]/{能力 or '模板'}",
                                item, item))
                break


def 找结构重复(node, path, out):
    """遍历所有「一串动作」的数组，逐数组查重复。

    查之前先**拍平 `顺序执行`**：它只声明「依次结算」，不产生新的结算点，留着会把
    同一结算点里本该合并的两笔账隔开（口径与 `fold.flatten_sequences` 一致）。

    还要查**跨分支**的重复：`尝试执行` 成功时会把 `尝试效果` 跑完再跑 `成功效果`
    （`mechanics._ability_attempt` 不回滚），所以同一个动作在两边各写一遍就是同一时点
    跑两遍（实测 2,155 处）。`失败效果` 不算——失败路径上 `尝试效果` 那一步没生效。
    """

    if isinstance(node, dict):
        if node.get("能力") == "尝试执行":
            成功 = {json.dumps(项, sort_keys=True, ensure_ascii=False)
                    for 项 in (node.get("成功效果") or ())}
            for 序, 项 in enumerate(node.get("尝试效果") or ()):
                if json.dumps(项, sort_keys=True, ensure_ascii=False) in 成功:
                    out.append(("尝试效果与成功效果重复", f"{path}/尝试效果[{序}]",
                                项, 项))
        for key, value in node.items():
            if key in SEQUENCE_KEYS and isinstance(value, list):
                检查序列(flatten_sequences(value), f"{path}/{key}", out)
            找结构重复(value, f"{path}/{key}", out)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            找结构重复(item, f"{path}/[{index}]", out)


def main() -> int:
    层 = load_rule_layer()
    实体数 = 0
    未支持: list = []
    泄漏: list = []
    结构重复: list = []
    渲染重复: list = []
    展开失败: list = []
    for 面, 目录, 模式 in SEGMENTS:
        for path in sorted(目录.glob(模式)):
            try:
                条目 = load_build_json(path)
            except Exception as exc:  # noqa: BLE001
                展开失败.append((面, path.name, str(exc)[:120]))
                continue
            for 实体 in (条目 if isinstance(条目, list) else [条目]):
                if not isinstance(实体, dict):
                    continue
                实体数 += 1
                编号 = 实体.get("编号")
                命中: list = []
                找结构重复(实体, "", 命中)
                for 类, 位置, 左, 右 in 命中:
                    结构重复.append((面, 编号, 类, 位置,
                                  json.dumps(左, ensure_ascii=False)[:80]))
                行 = list(render_body(实体, 层)[0]) + list(render_listeners(实体, 层)[0])
                缺失 = list(render_body(实体, 层)[1]) + list(render_listeners(实体, 层)[1])
                for 项 in 缺失:
                    # 渲染器认不出的节点（`〈未支持：…〉`）与**解释层兜底**（数据没写、
                    # 渲染器自己补的说法）都算「描述与设计不一致」，一律要红。
                    未支持.append((面, 编号, str(项)[:100]))
                for index, 行文 in enumerate(行):
                    if "未支持" in 行文:
                        未支持.append((面, 编号, 行文[:100]))
                    if "None" in 行文:
                        泄漏.append((面, 编号, 行文[:100]))
                    if index and 行文 == 行[index - 1]:
                        渲染重复.append((面, 编号, 行文[:100]))

    print(f"实体 {实体数} 个")
    print(f"展开失败 {len(展开失败)}")
    for x in 展开失败[:5]:
        print("   ", x)
    print(f"未支持 {len(未支持)}；None 泄漏 {len(泄漏)}")
    if 未支持:
        print("    （未支持 = 渲染器认不出的节点；兜底 = 数据没写、渲染器自己补的说法——两者都违反「描述与设计一模一样」）")
    for x in 未支持[:5]:
        print("   ", x)
    for x in 泄漏[:5]:
        print("   ", x)
    print(f"结构层重复 {len(结构重复)}")
    for k, v in collections.Counter(x[2] for x in 结构重复).most_common():
        print(f"    {k} x{v}")
    for x in 结构重复[:10]:
        print("    ", x[0], x[1], x[3], x[4])
    print(f"渲染层重复行 {len(渲染重复)}")
    for k, v in collections.Counter(x[2] for x in 渲染重复).most_common(10):
        print(f"    x{v}  {k}")
    return 1 if (展开失败 or 未支持 or 泄漏 or 结构重复 or 渲染重复) else 0


if __name__ == "__main__":
    raise SystemExit(main())
