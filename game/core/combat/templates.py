"""构筑模板：把重复的效果树收成「模板 + 参数」，在**装载期**展开成完整树。

## 它解决什么

实测：构筑三段（功法 / 真意 / 器律）共 458,062 行 JSON，但顶层效果的动作序列只有
**714 个原型**；最大的一个（「叠层 → 满层 → 引爆」）被抄了 **525 遍**。
模板化之后全六个面合计 **154,835 行**（省 341,369 行）。

于是卡里不再写整棵树，只写「用哪个模板 + 参数」：

```jsonc
{ "模板": "43c064ebe45c57", "参数": { "计量": "偷天养元", "层数": 2 } }
```

展开后与手写的那棵树**逐字节等价**——包括**键序**，因为键序决定卡面正文的措辞顺序。
键序与模板主体不同的实例，把差异写进引用自己的 `顺序` 键（见 `ORDER_KEY`）。

## 编号是内容地址，参数按位置

模板编号 = `body_digest(模板主体)`（`43` + sha256 前 12 位）。于是**重新生成库只会
新增/删除条目，永远不会让已有引用失效**：同一份主体永远得到同一个编号，旧引用只要
编号还在库里就照旧成立。

引用参数按**位置**写（`{"层数": 1}` 或 `{"/效果/[0]/层数": 1}`），不按出现顺序编号。
删掉一个字段不会让别的参数改号。

这两条都是踩过坑才改的：旧方案用「按面归一收益排名」发号、用 `p1`/`p2` 编号，数据一
变全体重编号，于是「换库」与「重挂引用」必须严格同步，拆开跑就毁数据（实测毁出 219 条
展不开的引用）。

## 展开在哪一步发生

在**装载期**：`JsonDataService.initialize` → `GameDataLoader.load(expand=…)` →
`game.core.combat.service.expand_build_section`，在快照冻结**之前**逐段展开。

这一步不能省：卡里可以只写引用，但快照里必须只有一种形态。曾经在
`CombatCatalog.parse_node`（解析期）展开，结果**校验与解析共用同一批可变对象**，
一处展开污染了别处（实测触发过启动期报错）。装载期一次展开成独立副本，校验、引擎、
战报、卡面渲染看到的都是同一个完整树。

**装载期只做展开，不做任何修正**：「一个结算点只算一次」由数据与模板主体保证
（见 `game.core.combat.fold`），解释层不替数据兜底。
"""

from __future__ import annotations


import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

#: 模板引用节点里标记模板编号的键。
TEMPLATE_KEY = "模板"
#: 模板引用节点里传参的键。
#:
#: 参数键是**位置路径或键名**（如 `/效果/[0]/层数` 或 `层数`），不是 `p1`/`p2` 这种按
#: 出现顺序编的号。
#:
#: 为什么必须这样：按顺序编号时，参数身份绑在「位置首次出现的顺序」上——数据里删掉
#: 一个字段，后面全体重编号，**所有引用同时失效**。实测这造成过 219 条引用展开不了、
#: 甚至一并改坏了数据。路径/键名是位置自身的性质，改别处不会动它。
PARAMETER_KEY = "参数"
#: 模板引用节点里记录**键序**的键：位置路径 -> 键的顺序。
#:
#: 为什么需要：键序在引擎里没有语义（按键取值），但**卡面正文按插入顺序输出**，
#: 所以「攻击+15、速度+12」和「速度+12、攻击+15」在玩家看到的地方是两句话。
#: 模板主体只能有一种键序，而原文自身并不处处自洽——实测 6624 条效果里有 1829 条
#: 在某处与多数序不同（平均 1.2 个对象）。这些位置若不记下来，展开结果就与原文不同。
#:
#: 只记**与模板主体不同**的那些对象，所以绝大多数引用没有这个键；有它的实测中位
#: 40 个字符。它让「展开后与原文逐字节相同」成为**引用自身的性质**，而不是迁移时
#: 偷偷补齐的巧合。
ORDER_KEY = "顺序"
#: 模板主体里占位符的键。
PLACEHOLDER_KEY = "$参数"
#: 占位符绑到这个值时，整个键从展开结果里删掉。
#:
#: 实测同一原型内部**并非完全同构**：原型 1 的 392 个实例有 4 种字段集合，
#: 21 个实例没有 `数值/最高值`、12 个没有 `每次行动最多触发`。所以参数分必填与可选，
#: 可选缺失时必须让展开结果里也没有那个键，否则会凭空补出字段、与原实例不等价。
OMIT = "<缺省>"

#: 模板编号前缀。后面接主体内容的哈希，所以编号本身**就是**内容的地址。
TEMPLATE_PREFIX = "43"

#: 模板库的类型别名。生成出来的 `template_data.py` 按它标注返回类型。
TemplateLibrary = dict[str, dict[str, Any]]


def param(name: str) -> dict[str, str]:
    """在模板主体里声明一个参数占位符。

    生成的模板库里用它代替字面值；展开时 `_materialize` 换成实参。
    """

    return {PLACEHOLDER_KEY: name}


def body_digest(body: Any, *, length: int = 12) -> str:
    """模板主体的**内容地址**。

    编号由主体内容唯一决定：同一份主体永远得到同一个编号，改一个字节就换编号。
    这样「重新生成库」只会新增/删除条目，**永远不会让已有引用失效**——旧引用只要它
    那个编号还在库里就照旧成立。

    曾经的编号是「按面归一收益排名」发的序号：数据一变、排名一变、全体重编号，于是
    换库与重挂引用必须严格同步，拆开跑就毁数据（实测毁出 219 条展不开的引用）。
    """

    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return TEMPLATE_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:length]


def paths_in(body: Any) -> list[str]:
    """主体里全部**标量叶子**的位置路径，按字典序。

    与生成器 `_shape`/`_derive_params` **同一口径**：只到标量为止，
    **占位符算作一个叶子、记它自己的路径**（不带额外后缀）。占位符叫什么名不该影响
    签名——实测两处口径不一会让同一簇算出不同签名，覆盖率掉到 925/23,252。
    """

    out: set[str] = set()

    def descend(current: Any, path: str) -> None:
        if isinstance(current, dict):
            if set(current) == {PLACEHOLDER_KEY}:
                out.add(path)
                return
            for key, value in current.items():
                descend(value, f"{path}/{key}")
        elif isinstance(current, list):
            for index, item in enumerate(current):
                descend(item, f"{path}/[{index}]")
        else:
            out.add(path)

    descend(body, "")
    return sorted(out)


def index_map(body: Any) -> dict[str, str]:
    """这份主体里 `位置路径 -> 参数名`。

    参数名取**键名**（路径最后一段）：写成 `{"层数": 1}` 比 `{"/效果/[0]/层数": 1}`
    短得多。同名键在这份主体里出现多次时**加序号**（`名称`、`名称2`、`名称3`）。

    **不再退回整条路径**。曾经的做法是重名就把位置编码进键名，于是库里 40% 的参数键
    成了 JSON 指针，最长那个 30 多字符（`/效果/[0]/成立效果/[0]/尝试效果/[0]/效果/[0]/数值/最高值`）。
    那是把「这句话在哪」写进了「这个名字叫什么」——位置信息本来就在模板主体里，
    键只需要一个**能对上号的标签**，不要求它跨位置唯一（只要求它在本份模板内唯一）。

    **只有占位符所在的位置算参数**。主体里那些写死的常量（`方式: "增加"`、`最高值: 100`）
    是模板的一部分、由所有实例共享，把它们也当参数会让引用多背一堆恒等实参——实测
    一份主体的 9 个标量里只有 3 个真会变，全当参数后 `restore_reference` 直接失配。
    """

    paths: list[str] = []

    def descend(current: Any, path: str) -> None:
        if isinstance(current, dict):
            if set(current) == {PLACEHOLDER_KEY}:
                paths.append(path)
                return
            for key, value in current.items():
                descend(value, f"{path}/{key}")
        elif isinstance(current, list):
            for index, item in enumerate(current):
                descend(item, f"{path}/[{index}]")

    descend(body, "")
    used: dict[str, int] = {}
    out: dict[str, str] = {}
    for path in paths:
        tail = path.rsplit("/", 1)[-1]
        order = used.get(tail, 0) + 1
        used[tail] = order
        out[path] = tail if order == 1 else f"{tail}{order}"
    return out


#: 机制词：原子能力名 -> 描述里用的说法。**只描述做什么，不带任何词条字眼**
#: （不出现「蓄元」「归元」这类随卡变化的东西）。
MECHANISM_WORDS: dict[str, str] = {
    "监听事件": "触发",
    "条件执行": "条件判定",
    "尝试执行": "尝试",
    "顺序执行": "依次",
    "随机执行": "随机",
    "重复执行": "重复",
    "事务执行": "事务",
    "遍历目标": "遍历",
    "消耗状态层数": "消耗层数",
    "增加状态层数": "叠加层数",
    "修改状态层数": "改动层数",
    "修改状态持续": "改动持续",
    "修改构筑计量": "改动计量",
    "添加状态": "赋予状态",
    "移除状态": "移除状态",
    "延长状态": "延长状态",
    "缩短状态": "缩短状态",
    "复制状态": "复制状态",
    "转移状态": "转移状态",
    "造成伤害": "造成伤害",
    "恢复资源": "恢复资源",
    "消耗资源": "消耗资源",
    "支付代价": "支付代价",
    "设置资源": "设置资源",
    "转移资源": "转移资源",
    "修改行动条": "推动行动条",
    "修改技能冷却": "改动技能冷却",
    "追加攻击": "追加攻击",
    "分摊伤害": "分摊伤害",
    "转移伤害": "转移伤害",
    "抵挡致命伤害": "抵挡致命伤害",
    "复活": "复活",
    "修改事件数值": "改动事件数值",
    "修改事件目标": "改动事件目标",
    "修改事件标签": "改动事件标签",
    "取消事件": "取消事件",
    "触发技能": "触发技能",
    "记录战斗事实": "记录战斗事实",
    "修改战斗关联": "改动战斗关联",
    "修改技能": "改动技能",
    "复制技能": "复制技能",
    "修改行动意图": "改动行动意图",
    "转化事件": "转化事件",
    "修改判定": "改动判定",
    "修改战场规则": "改动战场规则",
    "保存结果": "保存结果",
    "切换形态": "切换形态",
    "创建战斗对象": "召唤战斗对象",
    "移除战斗对象": "移除战斗对象",
    "修改归属": "改动归属",
    "回放效果": "回放效果",
    "修改战术": "改动战术",
}

#: 取数/选目标的管道动作，描述里跳过——它们不体现机制形状。
PIPELINE_ABILITIES = frozenset({
    "选择目标", "选择状态", "选择技能", "读取数值",
    "数值条件", "概率条件", "状态条件", "类型条件", "组合条件", "标签条件",
    "装配主动技能", "装配被动技能", "固定属性加成", "主动技能", "被动技能",
})


def describe(body: Any, *, limit: int = 6) -> str:
    """从模板主体生成一句人读的机制描述。

    描述**只讲机制形状**，不含任何词条字眼——所以它不会因为某张卡把「太乙蓄元」
    改名而失效。这就是它属于代码、而不属于数据的原因：它是**机制**的说明，
    不是**内容**的说明。
    """

    words: list[str] = []
    for ability in _ability_sequence(body):
        if ability in PIPELINE_ABILITIES:
            continue
        word = MECHANISM_WORDS.get(ability, ability)
        if word not in words:
            words.append(word)
    if not words:
        return "空机制"
    return " → ".join(words[:limit])


def _ability_sequence(node: Any) -> list[str]:
    """按与生成器一致的口径还原动作序列：先记自己，再按键名排序递归。"""

    out: list[str] = []

    def visit(current: Any) -> None:
        if isinstance(current, dict):
            ability = current.get("能力")
            if isinstance(ability, str):
                out.append(ability)
            for key in sorted(current):
                value = current[key]
                if isinstance(value, (dict, list)):
                    visit(value)
        elif isinstance(current, list):
            for item in current:
                visit(item)

    visit(node)
    return out


class TemplateError(ValueError):
    """模板引用不成立。"""


def expand_in_place(node: Any, templates: Mapping[str, Mapping[str, Any]]) -> Any:
    """把树里所有模板引用就地展开成完整树，返回同一个对象。

    引用节点形如 `{TEMPLATE_KEY: "430001", PARAMETER_KEY: {...}}`。
    展开是深度优先的，因此模板里若再引用别的模板也能解析；同时用 `chain`
    防止环形引用把解析拖死。
    """

    _expand(node, templates, ())
    return node


def _expand(node: Any, templates: Mapping[str, Mapping[str, Any]], chain: tuple[str, ...]) -> None:
    """就地展开树里所有模板引用。

    标量子节点**不进递归**：它既不是对象也不是数组，原实现也会递归进去、什么都不做就
    返回。实测一次启动这条递归要走 42 万个节点，其中大多数是标量叶子，那些调用全是
    白跑的函数调用开销。先按具体类型判（展开时的容器一律是 `dict`／`list`），落不到
    具体类型才退回抽象基类判据。
    """

    kind = type(node)
    if kind is dict or (kind is not list and isinstance(node, dict)):
        for value in node.values():
            child = type(value)
            if child is dict or child is list:
                _expand(value, templates, chain)
            elif (
                child is not str
                and child is not int
                and child is not float
                and child is not bool
                and value is not None
                and isinstance(value, (dict, list))
            ):
                _expand(value, templates, chain)
        if _is_reference(node):
            _substitute(node, templates, chain)
    elif kind is list or isinstance(node, list):
        for item in node:
            child = type(item)
            if child is dict or child is list:
                _expand(item, templates, chain)
            elif (
                child is not str
                and child is not int
                and child is not float
                and child is not bool
                and item is not None
                and isinstance(item, (dict, list))
            ):
                _expand(item, templates, chain)


def _is_reference(node: Mapping[str, Any]) -> bool:
    return TEMPLATE_KEY in node and node.get(TEMPLATE_KEY) is not None


def _substitute(node: dict, templates: Mapping[str, Mapping[str, Any]], chain: tuple[str, ...]) -> None:
    template_id = str(node[TEMPLATE_KEY])
    if template_id in chain:
        raise TemplateError(f"构筑模板形成循环引用：{' -> '.join((*chain, template_id))}")
    raw = templates.get(template_id)
    if raw is None:
        raise TemplateError(f"构筑模板不存在：{template_id}")

    body_template = raw.get("主体")
    bound = bind_parameters(template_id, node.get(PARAMETER_KEY), body_template, raw)
    # **不必再深拷贝**：`_materialize` 对每个对象与数组都构造新容器，等价于一次
    # 「边拷贝边替换占位符」，返回的树与模板库里的对象不共享任何可变容器。原先多做的
    # 那一次 `copy.deepcopy` 是纯开销——它先复制一份，`_materialize` 再把复制品整个重建。
    # 两者只在模板主体含**元组**时才有差别（元组不被 `_materialize` 重建），而模板库由
    # JSON 生成、只有对象与数组。
    body = _materialize(body_template, bound, template_id)
    order = node.get(ORDER_KEY)
    if isinstance(order, Mapping):
        body = _order_by_spec(body, order)
    node.clear()
    node.update(body)
    # 模板主体里若再引用别的模板，继续展开；`chain` 防止环形引用。
    _expand(node, templates, (*chain, template_id))


def bind_parameters(
    template_id: str,
    provided: Any,
    body: Any,
    _template: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """把引用的实参绑到模板主体声明的占位符上。

    实参的键是**位置**（键名或路径，见 `PARAMETER_KEY`），模板主体里的占位符名是
    生成时按同一口径算出来的（`index_map`）。两者对上就把值交给 `_materialize`。

    三种键名不匹配一律报错、**绝不静默忽略**：静默忽略会让展开结果悄悄少一个值，
    那是最难查的一类坏数据（实测「缺参数」是换库时最早暴露的症状）。
    """

    if provided is None:
        provided = {}
    if not isinstance(provided, Mapping):
        raise TemplateError(f"构筑模板 {template_id} 的参数必须是对象")

    alias = _parameter_alias(template_id, body)
    bound: dict[str, Any] = {}
    for key, value in provided.items():
        card_name = alias.get(str(key))
        if card_name is None:
            raise TemplateError(
                f"构筑模板 {template_id} 没有参数位置：{key}"
            )
        bound[card_name] = value
    return bound


#: `位置/短名 -> 占位符名` 的别名表缓存。
#:
#: 别名表只由**模板主体**决定，与实参无关，而同一份主体在一次启动里要被展开成百上千
#: 次（实测 8472 次展开、1299 份主体）。原先每次重算 `_placeholders` 与 `index_map`，
#: 两次都是对整份主体递归拼路径字符串。这里按编号缓存，并用 `is` 校验主体仍是同一对象：
#: 模板库重新生成后编号不变而对象换新时，缓存自动失效。
_ALIAS_CACHE: dict[str, tuple[Any, dict[str, str]]] = {}


def _parameter_alias(template_id: str, body: Any) -> dict[str, str]:
    """`实参键 -> 占位符名`。实参的键认三种写法：**占位符名**（`p1`）、**短名**
    （`层数` / `名称2`）、**位置路径**（`/效果/[0]/层数`）。落盘用的是短名。

    短名**现算**，不在模板库里另存一份参数表：存了就要跟主体永远保持一致，
    那正是「一句话写两遍」——实测已经漂移过（219 条引用展不开）。
    """

    cached = _ALIAS_CACHE.get(template_id)
    if cached is not None and cached[0] is body:
        return cached[1]

    true_name = _placeholders(body)
    alias: dict[str, str] = {}
    for position, card_name in true_name.items():
        alias.setdefault(card_name, card_name)
        alias.setdefault(position, card_name)
    for position, short_name in index_map(body).items():
        alias.setdefault(short_name, true_name[position])
    _ALIAS_CACHE[template_id] = (body, alias)
    return alias


def _bindings_from_original(body: Any, original: Any) -> dict[str, Any]:
    """按模板主体的占位符位置，从 `original` 里取实参。

    键用 `index_map` 给出的**短名**（`名称` / `名称2` / `层数`）——那是给人读的，
    不必是占位符名（`p1`）。短名与占位符名做不到一一对应时（两份不同的短名撞到同一个
    占位符名）才退回占位符名，保证不会绑错。
    """

    short_name = index_map(body)
    true_name = _placeholders(body)
    out: dict[str, Any] = {}
    reverse_counts: dict[str, int] = {}
    for card_name in true_name.values():
        reverse_counts[card_name] = reverse_counts.get(card_name, 0) + 1
    for position, card_name in true_name.items():
        key = short_name.get(position, card_name)
        if reverse_counts.get(card_name, 0) > 1:
            key = card_name
        value = _leaf(original, position)
        out[key] = OMIT if value is _MISSING else value
    return out


def _order_by_spec(node: Any, order: Mapping[str, Any]) -> Any:
    """按引用里记下的键序重排展开结果。

    顺序表只列**与模板主体不同**的对象，路径形如 `/效果/[1]/状态/属性`；其余对象
    保持模板主体的键序。递归下去，因为一个对象顺序变了，它内部的对象可能也要变。
    """

    if not order:
        return node
    return _reorder_at(node, "", order)


def _reorder_at(node: Any, path: str, order: Mapping[str, Any]) -> Any:
    """递归处理：当前路径若在顺序表里就按它重排，否则只把顺序下传给子节点。

    不能按「路径是否是顺序表键的前缀」剪枝：顺序表只列有差异的对象，而差异对象可能
    嵌在无差异对象里面。
    """

    if isinstance(node, dict):
        wanted = None
        if path in order and isinstance(order[path], list):
            spec = order[path]
            # 只在键集**完全一致**时按记录重排：参数值可能是对象，而实参自身已带
            # 原卡键序；位置对不上就说明这条记录不该管这里，保持现状更安全。
            if set(spec) == set(node):
                wanted = list(spec)
        if wanted is None:
            wanted = list(node)
        return {
            key: _reorder_at(node[key], f"{path}/{key}", order)
            for key in wanted
        }
    if isinstance(node, list):
        return [
            _reorder_at(item, f"{path}/[{index}]", order)
            for index, item in enumerate(node)
        ]
    return node


def _materialize(node: Any, bound: Mapping[str, Any], template_id: str) -> Any:
    """把占位符换成实参；绑到 `OMIT` 的占位符返回哨兵，由上层删键。

    判占位符用 `len(node) == 1 and PLACEHOLDER_KEY in node`，**不要**写
    `set(node) == {PLACEHOLDER_KEY}`：那会给每一个对象节点都现造一个集合，
    实测一次启动要过 28 万个节点。
    """

    if isinstance(node, dict):
        if len(node) == 1 and PLACEHOLDER_KEY in node:
            name = str(node[PLACEHOLDER_KEY])
            if name not in bound:
                return _raise_missing(template_id, name)
            return _OMITTED if bound[name] == OMIT else bound[name]
        result: dict[str, Any] = {}
        for key, value in node.items():
            filled = _materialize(value, bound, template_id)
            if filled is _OMITTED:
                continue
            result[key] = filled
        return result
    if isinstance(node, list):
        return [
            filled for item in node
            if (filled := _materialize(item, bound, template_id)) is not _OMITTED
        ]
    return node


def _raise_missing(template_id: str, name: str) -> Any:
    raise TemplateError(f"构筑模板 {template_id} 缺少参数：{name}")


class _Omitted:
    """占位符绑到 `OMIT` 时的内部哨兵。"""


_OMITTED = _Omitted()


def order_diff(expanded: Any, original: Any) -> dict[str, list[str]]:
    """展开结果里**键序与原文不同**的对象：位置路径 -> 原文的键序。

    只列不同的那些，绝大多数引用因此没有 `顺序` 键（实测 6624 条里 1829 条需要，
    平均 1.2 个对象、中位 40 个字符）。
    """

    out: dict[str, list[str]] = {}

    def visit(node: Any, want: Any, path: str) -> None:
        if isinstance(node, dict) and isinstance(want, dict):
            if set(node) == set(want) and list(node) != list(want):
                out[path] = list(want)
            for key in node:
                if key in want:
                    visit(node[key], want[key], f"{path}/{key}")
        elif isinstance(node, list) and isinstance(want, list):
            for index in range(min(len(node), len(want))):
                visit(node[index], want[index], f"{path}/[{index}]")

    visit(expanded, original, "")
    return out


def restore_reference(
    template_id: str,
    body: Any,
    original: Any,
    templates: Mapping[str, Mapping[str, Any]],
    *,
    order: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """拼一个能**无损还原** `original` 的引用；做不到就返回 None。

    这是「引用是否成立」的**唯一判据**，校验、生成与迁移共用同一份，避免出现
    「生成说能还原、迁移却拒收」这种两边判据脱节（实测发生过两次：一次是生成器
    用 `sort_keys` 比、一次是迁移用 `reorder_like` 兜底）。

    成立的定义就是**装载期展开后与原文逐字节相同**——包括键序，因为键序决定卡面
    正文的措辞顺序。展开结果与原文只差键序时，把差异写进引用的 `顺序` 键再验一次。

    实参**从 `original` 里按位置取**（位置由 `index_map(body)` 给出），所以调用方
    不必知道参数怎么编号——这是内容寻址的关键：参数身份属于位置，不属于编号顺序。
    """

    reference: dict[str, Any] = {
        TEMPLATE_KEY: template_id,
        PARAMETER_KEY: _bindings_from_original(body, original),
    }
    if order:
        # 键序差异由调用方传入（生成器会在第一次比较后重试）。
        reference[ORDER_KEY] = dict(order)
    probe = copy.deepcopy(reference)
    try:
        expand_in_place(probe, templates)
    except Exception:  # noqa: BLE001 - 任何异常都视为引用不成立
        return None
    diff = order_diff(probe, original)
    if diff and not order:
        reference[ORDER_KEY] = diff
        probe = copy.deepcopy(reference)
        try:
            expand_in_place(probe, templates)
        except Exception:  # noqa: BLE001
            return None
        probe.pop(ORDER_KEY, None)
    return reference if probe == original else None


def _placeholders(body: Any) -> dict[str, str]:
    """`位置路径 -> 占位符名`。"""

    out: dict[str, str] = {}

    def descend(current: Any, path: str) -> None:
        if isinstance(current, dict):
            if set(current) == {PLACEHOLDER_KEY}:
                out[path] = str(current[PLACEHOLDER_KEY])
                return
            for key, value in current.items():
                descend(value, f"{path}/{key}")
        elif isinstance(current, list):
            for index, item in enumerate(current):
                descend(item, f"{path}/[{index}]")

    descend(body, "")
    return out


class _MissingValue:
    pass


_MISSING = _MissingValue()


def _leaf(node: Any, path: str) -> Any:
    """按位置路径取值；位置不存在时返回哨兵。路径形如 `/效果/[0]/层数`。"""

    current = node
    for part in [p for p in path.split("/") if p]:
        if part.startswith("[") and part.endswith("]"):
            if not isinstance(current, list) or int(part[1:-1]) >= len(current):
                return _MISSING
            current = current[int(part[1:-1])]
            continue
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


def reorder_like(expanded: Any, original: Any) -> Any:
    """把展开结果按照原文的键序重排，返回新对象。

    用于让**参数值**（可能是对象，如 `状态.属性`）带上原卡的键序，使引用在装载期
    展开后与原文逐字节相同。
    """

    if isinstance(expanded, dict):
        # 原值可能是标量而展开值是对象（或反之）。这种时候仍要**递归**下去，
        # 否则嵌套对象的键序得不到处理，读取方展开后就会与原文不同。
        ordered: dict[str, Any] = {}
        if isinstance(original, dict):
            for key in original:
                if key in expanded:
                    ordered[key] = reorder_like(expanded[key], original[key])
        for key, value in expanded.items():
            if key not in ordered:
                ordered[key] = reorder_like(
                    value, original.get(key) if isinstance(original, dict) else None
                )
        return ordered
    if isinstance(expanded, list):
        return [
            reorder_like(
                item,
                original[index] if isinstance(original, list) and index < len(original) else None,
            )
            for index, item in enumerate(expanded)
        ]
    return expanded


__all__ = [
    "MECHANISM_WORDS",
    "OMIT",
    "ORDER_KEY",
    "PARAMETER_KEY",
    "PIPELINE_ABILITIES",
    "TEMPLATE_KEY",
    "TEMPLATE_PREFIX",
    "TemplateError",
    "TemplateLibrary",
    "bind_parameters",
    "body_digest",
    "describe",
    "expand_in_place",
    "index_map",
    "order_diff",
    "param",
    "paths_in",
    "reorder_like",
    "restore_reference",
]
