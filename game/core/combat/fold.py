"""一个时点只算一次：把重复的增量动作并掉（**数据与模板层**规范化）。

## 规则

引擎的时点是**单次结算**：同一个效果数组里的相邻动作在同一个时点依次结算，而
「同一个计量的加法」「同一个状态的叠层」在这个时点上只可能发生一次。所以数据里
把 `+1` 与 `+18` 写成两笔，机制上不是两次加法，只是同一个动作被拆成了两笔——
按设计口径要合成 `+19`。同一个时点上把同一个动作写两遍，还容易让
「变化后触发」类监听互相勾连、转成死循环。

只有**加法**受这条规则约束：

* `修改构筑计量` / `增加状态层数`（同目标、同计量、同方向）→ 合成一笔，量相加；
* `造成伤害` / `追加攻击`（攻击次数）、`添加状态`、多个不同监听等 → **不合并**，
  连写两次就是打两下、加两个；
* `遍历目标` / `恢复资源` 一字不差连写两遍 → 删一份（一个时点只做一次的资源动作，
  重写一遍纯属复制错误）。

## 这是数据层的事，不是解释层的事

**装载期与渲染层都不在这里折叠**：

* 渲染器是只读的，只输出数据里真实存在的东西。在它那儿合并等于把数据的毛病盖住，
  下一个人照抄一遍照样出（`card_text.py` 里曾经加过、已撤掉）。
* 装载期只负责把模板引用展开成完整树。

所以这条规则必须由**数据与模板主体**满足：`tools/构筑模板.py` 的收集与迁移共用
本模块这一份实现，模板主体也要过 `fold_template_library.py` 那一遍。
"""

from __future__ import annotations

import json
from typing import Any

ABILITY = "能力"
TEMPLATE_KEY = "模板"

#: 一个时点上只可能发生一次的**加法**动作。
INCREMENTS = ("修改构筑计量", "修改状态层数")

#: 逐字节相同就删一份的单次资源动作。
SINGLE = ("遍历目标", "遍历", "恢复资源")

#: 增量的量词字段。
_AMOUNT_KEY = {"修改构筑计量": "数值", "修改状态层数": "层数"}

#: 「一串动作」的字段名。`顺序执行` 的子项与父数组属于**同一个结算点**，
#: 所以归一化时要拍平；其余字段（`选项` 等）各有自己的语义，不拍。
_SEQUENCE_KEYS = ("效果",)


def flatten_sequences(node: Any) -> Any:
    """把 `顺序执行` 的子项拍进它所在的数组。

    为什么必须拍：`顺序执行` 只声明「这些动作依次结算」，**不产生一个新的结算点**。
    把它留着会让「同一个结算点上同一计量的两笔加法」被它隔开，从而躲过合并——
    实测 143 处计量 + 143 处层数就是这样漏的（`[+20, …, +13]` 本该是 `+33`）。

    拍平是**语义等价**的：渲染的 `_sequence` 遇到 `顺序执行` 本来就继续拆成 `•` 条目，
    所以卡面文本一个字不变。嵌套的 `顺序执行` 实测 0 处，仍按递归处理。

    拍平后父数组里的每个元素都是**同一个结算点**的动作；分支（条件/尝试/随机）里的
    数组各自是独立结算点，本函数只拍 `效果`，不跨分支。
    """

    if isinstance(node, dict):
        return {
            key: (
                [flatten_sequences(x) for x in _expand(item)]
                if key in _SEQUENCE_KEYS and isinstance(item, list)
                else flatten_sequences(item)
            )
            for key, item in node.items()
        }
    if isinstance(node, list):
        return [flatten_sequences(x) for x in _expand(node)]
    return node


def _expand(items: Any) -> list:
    """把数组里的 `顺序执行` 摊平成它的子项（递归）。"""

    if not isinstance(items, list):
        return items
    out: list = []
    for item in items:
        if isinstance(item, dict) and item.get(ABILITY) == "顺序执行":
            child = item.get("效果")
            if isinstance(child, list):
                out.extend(_expand(child))
                continue
        out.append(item)
    return out


def fold_repeats(node: Any) -> Any:
    """整棵树过一遍「同一结算点只算一次」，返回新树。

    两步：先把 `顺序执行` 拍平（它不产生新结算点），再在同一数组内按**计量/状态键**
    合并增量。合并**不要求相邻**——同一个结算点上同一计量的两笔加法，中间隔着
    「建立关联」「记录事实」这类动作也仍然是同一个动作的两半（实测 143 处计量 +
    143 处层数正是被这些动作隔开的）。
    """

    node = flatten_sequences(node)
    return _fold_walk(node)


def _fold_walk(node: Any) -> Any:
    if isinstance(node, dict):
        if TEMPLATE_KEY in node:
            return node
        return {key: _fold_walk(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_fold_walk(item) for item in _merge_same_counter(_fold_identical(node))]
    return node


def _merge_same_counter(items: list) -> list:
    """同一数组内按**计量/状态键**合并增量，不要求相邻。

    先递归折好每个子项（子项内部也要合），再按顺序、按键把增量并到该键的**首次出现
    位置**上，其余位置删除。保持「第一次加」的位置，是因为它决定了这个动作在这段
    结算里的先后；把结果挪到末尾会改变它与中间其它动作的相对次序。
    """

    result: list = []
    position: dict[tuple, int] = {}
    for item in items:
        item = _fold_walk(item)
        if isinstance(item, dict) and isinstance(item.get(ABILITY), str) \
                and item[ABILITY] in INCREMENTS:
            # 键**不带方向**：`+2` 与 `-2` 是同一个计量上的两笔，合起来才是净结果。
            # 带上方向会让它们落进不同的桶、永远碰不上面（实测算出「+2 记a -2」）。
            key = _counter_key(item, item[ABILITY])
            index = position.get(key)
            if index is not None:
                merged = fold_increment(result[index], item)
                if merged is not None:
                    if merged:
                        result[index] = merged
                    else:
                        # 互相抵消：这个结算点上什么都不做，两条都去掉。
                        result.pop(index)
                        for k in position:
                            if position[k] > index:
                                position[k] -= 1
                        position.pop(key, None)
                    continue
            position[key] = len(result)
        result.append(item)
    return result


def _fold_identical(items: list) -> list:
    """同一结算点里**逐字节相同**的动作只留一份。

    不要求相邻。同一条规定（同一结算点不出重复动作）既管增量、也管完全相同的动作；
    只查相邻会漏掉被别的动作隔开的重复（实测 `天魔解体丹` / `同纹寄诀丹` 各有两条
    一字不差的「恢复护盾」，中间隔着一条「恢复血气」）。

    为什么这里连 `追加攻击` 也删：同一个结算点上两次**完全相同**的追加攻击是同一个
    动作写了两遍。要打两下就写成两下有别的含义的写法（不同威力倍率/不同目标），
    而不是把同一条复制一遍。模板引用同理——同一模板、同一实参，展开后就是同一个
    动作做两次。
    """

    out: list = []
    seen: list = []
    for item in items:
        if isinstance(item, dict):
            if item in seen:
                continue
            seen.append(item)
        out.append(item)
    return out


def fold_increment(left: Any, right: dict) -> dict | None:
    """同一时点上同一计量的两次改动并成一笔；不能并则返回 `None`。

    三种形态：

    1. **两边都是「增加」**（`增加状态层数` 或 `修改构筑计量` 方式=增加）→ 量相加。
       两边都是字面数字就直接相加；有一边是能力（如 `读取数值`）就包一层
       `计算数值(相加)`——`修改构筑计量.数值` 的字段类型本来就是「数值或能力」。
       `增加状态层数.层数` 要求整数，遇到能力时不并，交给它自己的字段约束去挡。
    2. **先「设置」后「增加」** → 设置那笔被紧跟的增加作废（设置完立刻又被加上去，
       设置值等于没写），只留增加那笔。反过来「设置」后面跟「减少」不能这么算
       （`设置为12` 再 `减少1` 是 11，不是原值减 1），那种不并。
    3. 其余（方向不同、上限不同）→ 不并。

    改完之后数值是参数占位（`{"$参数": …}`）时不并：模板主体里那种
    `[+1, +参数p3]` 由**展开之后**的这里各自合并。
    """

    if not isinstance(left, dict):
        return None
    ability = right.get(ABILITY)
    if ability not in INCREMENTS or left.get(ABILITY) != ability:
        return None
    amount = _AMOUNT_KEY[ability]
    a, b = left.get(amount), right.get(amount)
    limit = _widest_cap(left, right, ability)
    leftward, rightward = _way(left), _way(right)

    # 「设置」后面紧跟同一个计量的增减：设置值立刻被覆盖，那一笔在结算上没有落点，
    # 属于同一个结算点里的重复动作。只留后面那笔增减。
    if leftward == "设置" and rightward in ("增加", "减少") and _same_counter(left, right, ability):
        merged = json.loads(json.dumps(right, ensure_ascii=False))
        _apply_cap(merged, limit, ability)
        return merged

    if leftward not in ("增加", "减少") or rightward not in ("增加", "减少"):
        return None
    if _placeholder(a) or _placeholder(b):
        return None
    if isinstance(a, bool) or isinstance(b, bool):
        return None

    # **先把方向定下来再判等**。`_same_counter` 里带 `方式` 比较（加法与加法才是
    # 同一个动作），所以「减少1 与 增加2」这种要先算出净方向、写成那一笔，再去比；
    # 顺序反了会拿 `左向 != 右向` 直接判不成立，把该并的漏掉（实测算出 +3 而不是 +1）。
    net = None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        net = (a if leftward == "增加" else -a) + (b if rightward == "增加" else -b)
    merged_after = json.loads(json.dumps(right, ensure_ascii=False))
    if net is not None:
        # 两个能力现在都有 `方式` 字段，写它就是写方向。净量为 0 时这个结算点上
        # 什么都不做——删掉整条比留一条 `方式: 减少, 层数: 0` 干净（后者还会被
        # 卡面渲染成「消耗0层」）。
        if net == 0:
            return {}
        merged_after["方式"] = "增加" if net > 0 else "减少"
        merged_after[amount] = abs(net)
    if not _same_counter(left, merged_after, ability):
        return None

    if net is not None:
        _apply_cap(merged_after, limit, ability)
        return merged_after

    if leftward != "增加" or rightward != "增加":
        # 有一边是能力节点时不做有符号运算：`增加 读取X` 与 `减少 2` 的净量要写成
        # `计算数值(相减)`，而 `减少 读取X` 还要取负，属于过度推演。这类不并。
        return None
    if ability != "修改构筑计量":
        # `修改状态层数.层数` 是整数，装不下 `计算数值`。
        return None
    if not _is_value_node(a) or not _is_value_node(b):
        return None
    merged_after[amount] = {
        "能力": "计算数值",
        "方式": "相加",
        "左值": _as_value(a),
        "右值": _as_value(b),
    }
    _apply_cap(merged_after, limit, ability)
    return merged_after


def _same_counter(left: dict, right: dict, ability: str) -> bool:
    """两笔是不是同一个计量/同一个状态（**不管方向、不管上限**）。

    `设置 12` 与 `减少 1` 也是同一个计量上的两笔——「设置被紧随的增减覆盖」这条规则
    靠的就是不比较方向。
    """

    if ability == "修改构筑计量":
        return (
            json.dumps(left.get("目标"), sort_keys=True, ensure_ascii=False),
            json.dumps(left.get("计量"), ensure_ascii=False),
        ) == (
            json.dumps(right.get("目标"), sort_keys=True, ensure_ascii=False),
            json.dumps(right.get("计量"), ensure_ascii=False),
        )
    return json.dumps(left.get("状态"), sort_keys=True, ensure_ascii=False) == \
        json.dumps(right.get("状态"), sort_keys=True, ensure_ascii=False)


def _widest_cap(left: dict, right: dict, ability: str) -> float | None:
    """合并后取两者**较宽**的上限。

    并成一笔后只结算一次，若用较窄的那个上限，结果会比原来更早封顶——那是改机制。
    """

    if ability != "修改构筑计量":
        return None
    caps = [
        float(node["最高值"]) for node in (left, right)
        if isinstance(node.get("最高值"), (int, float))
        and not isinstance(node["最高值"], bool)
    ]
    return max(caps) if caps else None


def _apply_cap(node: dict, cap: float | None, ability: str) -> None:
    if cap is None or ability != "修改构筑计量":
        return
    node["最高值"] = int(cap) if float(cap).is_integer() else cap


def _way(node: dict) -> str:
    """这个动作的方向。**两个增量能力都读 `方式` 字段**，没有默认方向。

    曾经这里对非 `修改构筑计量` 的能力一律返回「增加」——那是 `增加状态层数` /
    `消耗状态层数` 两个能力名还在的年代，方向写在名字里、字段里没有。两者合并成
    `修改状态层数` 之后必须读字段，否则「减少」会被读成「增加」（实测把
    `增加2+减少2` 算成 `+4`）。
    """

    return str(node.get("方式") or "")


def _placeholder(value: Any) -> bool:
    return isinstance(value, dict) and any(key.startswith("$") for key in value)


def _is_value_node(value: Any) -> bool:
    """这个值能不能当作 `计算数值` 的操作数：字面数字或能力节点。"""

    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, dict):
        return isinstance(value.get(ABILITY), str) or _placeholder(value)
    return False


def _as_value(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _counter_key(node: dict, ability: str) -> tuple:
    """「同一笔账」的判等键：目标 + 计量/状态。**不带方向、不带上限**。

    方向不带：`+2` 与 `-2` 是同一个账上的两笔，合起来才是净结果。
    上限不带：上限不同只说明两笔的封顶写法不一致，合并时取较宽的即可
    （见 `_widest_cap`）。
    """

    if ability == "修改构筑计量":
        return (
            json.dumps(node.get("目标"), sort_keys=True, ensure_ascii=False),
            json.dumps(node.get("计量"), ensure_ascii=False),
        )
    return (json.dumps(node.get("状态"), sort_keys=True, ensure_ascii=False),)


__all__ = ["INCREMENTS", "SINGLE", "flatten_sequences", "fold_increment", "fold_repeats"]
