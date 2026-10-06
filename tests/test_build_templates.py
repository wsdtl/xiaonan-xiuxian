"""构筑模板：**内容寻址**的回归测试。

模板机制的判据是**逐字节回环**：模板主体 + 实参展开出来的结果，必须与原文完全相同
——**包括键序**，因为键序决定卡面正文的措辞顺序（`攻击+15、速度+12` 与
`速度+12、攻击+15` 不是同一句话）。判据用 `templates.restore_reference`，与生成器、
迁移工具**同一份**。

## 内容寻址锁住什么

1. **编号就是主体内容的地址**：`body_digest(主体) == 编号`。于是「重新生成库」只会
   新增/删除条目，**永远不会让已有引用失效**——旧引用只要编号还在库里就照旧成立。
   旧方案用「按面归一收益排名」发号，数据一变全体重编号，换库与重挂引用必须严格同步，
   拆开跑就毁数据（实测毁出 219 条展不开的引用）。
2. **参数按位置**：引用的参数键是键名或位置路径（`{"层数": 1}`），不是 `p1`/`p2`
   这种按出现顺序编的号。删掉一个字段不会让别的参数改号。
3. **每个模板的每个实例都能无损还原**：`restore_reference` 是唯一判据。

同时锁住两条实测踩过的坑：

* **深拷贝**：展开若浅拷贝模板主体，第一遍就会把 `{"$参数": …}` 换成具体值，同一个
  模板第二次展开便拿不到占位符。
* **可选参数**：参数缺失时展开结果里也不能有那个键，否则会凭空补出字段。
"""

from __future__ import annotations

import copy
import json

import pytest

from game.core.combat import templates as 模板模块
from game.core.combat.template_data import (
    TEMPLATE_CLUSTERS,
    TEMPLATE_FACES,
    library,
)

param = 模板模块.param


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def test_every_template_id_is_its_body_digest() -> None:
    """编号必须等于主体内容的哈希——这是「重新生成库不会让引用失效」的前提。"""

    库 = library()
    assert len(库) > 100, f"库太小，样本异常：{len(库)}"   # 护栏只防"库被删空"，与粒度无关
    错 = [
        编号 for 编号, 条目 in 库.items()
        if 模板模块.body_digest(条目["主体"]) != 编号
    ]
    assert not 错, f"这些模板的编号与主体哈希不符：{错[:5]}"


def test_template_ids_stable_under_body_round_trip() -> None:
    """主体原样搬运后编号不变；改一个字节就换编号。"""

    库 = library()
    编号 = next(iter(库))
    主体 = 库[编号]["主体"]
    assert 模板模块.body_digest(copy.deepcopy(主体)) == 编号

    # 找一个标量叶子改掉；找不到就换下一个模板（有的主体全是占位符）
    for 编号2, 条目 in 库.items():
        候选 = copy.deepcopy(条目["主体"])
        叶子 = _first_scalar_path(候选)
        if 叶子 is None:
            continue
        _set_path(候选, 叶子, "改动过的值")
        assert 模板模块.body_digest(候选) != 编号2
        break


def test_cluster_catalog_maps_shape_to_template() -> None:
    """结构签名目录与库一一对应，迁移靠它把一条效果定位到模板。"""

    库 = library()
    assert set(TEMPLATE_CLUSTERS) == set(库)
    assert set(TEMPLATE_FACES) == set(库)
    for 编号, (序列, 路径) in TEMPLATE_CLUSTERS.items():
        assert isinstance(序列, list) and isinstance(路径, list)
        # 序列与路径都要能从主体现算出来，否则迁移会定位到错的模板
        assert list(模板模块.describe(库[编号]["主体"])) != []
        assert 模板模块.index_map(库[编号]["主体"]) is not None


def test_parameter_positions_are_derived_not_stored() -> None:
    """参数位置**从主体现算**，库里不另存一份。

    存一份就要永远保持一致，那是「一句话写两遍」——实测漂移过（219 条引用展不开）。
    这条测试同时锁住「现算出来的位置与占位符一一对应」。
    """

    错 = []
    for 编号, 条目 in library().items():
        if "参数位置" in 条目:
            错.append((编号, "库里不该存参数位置"))
            continue
        推导 = set(模板模块.index_map(条目["主体"]))
        实际 = set(_placeholder_paths(条目["主体"]))
        if 推导 != 实际:
            错.append((编号, sorted(推导 ^ 实际)[:3]))
    assert not 错, f"参数位置推导与占位符不符：{错[:5]}"


def test_cluster_paths_are_derivable_from_body() -> None:
    """簇表里的叶子路径表必须能从主体现算——它是迁移的匹配键。"""

    from game.core.combat.templates import paths_in

    错 = [
        编号 for 编号, (_序列, 路径) in TEMPLATE_CLUSTERS.items()
        if paths_in(library()[编号]["主体"]) != list(路径)
    ]
    assert not 错, f"簇叶子路径表与主体不一致：{错[:5]}"


def test_every_template_body_round_trips() -> None:
    """每份模板都要能为自己拼出一条无损引用。

    判据是 `restore_reference`：拼出的引用展开后必须与「原文」逐字节相同。这里用
    模板主体**自己**当原文——它恰好是最严格的一类样本（占位符全在，所有位置都非缺省）。
    这样测试不依赖 `data/` 处于「已迁移」还是「已展开」形态。
    """

    库 = library()
    坏: list[str] = []
    for 编号, 条目 in 库.items():
        主体 = 条目["主体"]
        子库 = {编号: 条目}
        引用 = 模板模块.restore_reference(编号, 主体, 主体, 子库)
        if 引用 is None:
            坏.append(编号)
            continue
        节点 = copy.deepcopy(引用)
        模板模块.expand_in_place(节点, 子库)
        if _dumps(节点) != _dumps(主体):
            # 主体自己作为原文时，缺省参数会以 OMIT 形式出现，展开后少键——这不算坏，
            # 只有「多出/改动了值」才算。逐字节相等是常态，不等时记录待人工确认。
            坏.append(f"{编号}(展开不一致)")
    assert len(库) > 100, f"库太小，样本异常：{len(库)}"   # 护栏只防"库被删空"，与粒度无关
    assert not 坏, f"这些模板拼不回引用：{坏[:8]}"


def test_data_references_point_at_existing_templates() -> None:
    """数据里的每个引用都指向现行库里的编号（两种数据形态下都成立）。

    已迁移时数据里是引用、已展开时一条都没有——两种都不该报错。
    """

    from pathlib import Path as _Path
    import sys as _sys

    _tools = str(_Path(__file__).resolve().parents[1] / "tools")
    if _tools not in _sys.path:
        _sys.path.insert(0, _tools)
    import 构筑模板 as 构筑

    库 = library()
    总数 = 0
    缺失: list[str] = []
    for 面, 配置 in 构筑.SEGMENTS.items():
        for path in sorted(配置["目录"].glob(配置["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            for 实体 in (文档 if isinstance(文档, list) else [文档]):
                if not isinstance(实体, dict):
                    continue
                for 引用 in _collect_references(实体):
                    总数 += 1
                    编号 = str(引用["模板"])
                    if 编号 not in 库:
                        缺失.append(编号)
    assert not 缺失, f"引用了库里没有的编号：{sorted(set(缺失))[:8]}"


def test_expansion_is_repeatable() -> None:
    """同一份模板连续展开多次结果一致。

    这锁住「展开污染模板库」那个坑：浅拷贝模板主体时，第一遍就把占位符换成了
    具体值，第二遍便再也拿不到 `{"$参数": …}`。
    """

    库 = library()
    编号 = next(iter(库))
    主体 = 库[编号]["主体"]
    参数表 = {
        名字: "值" for 名字 in _placeholder_paths(主体).values()
    }
    第一次 = 模板模块._materialize(copy.deepcopy(主体), 参数表, 编号)
    第二次 = 模板模块._materialize(copy.deepcopy(主体), 参数表, 编号)
    assert _dumps(第一次) == _dumps(第二次)
    # 模板库里的主体没有被污染
    assert _dumps(库[编号]["主体"]) == _dumps(主体)


def test_order_override_keeps_original_key_order() -> None:
    """键序与模板主体不同的实例，靠引用自己的 `顺序` 键还原。

    没有它，落盘的引用在装载期会展开成模板主体的键序，卡面正文的措辞顺序就变了。
    场景**直接构造**而不是从库里取样：现在的簇按结构签名切分（同簇内字段集合完全
    一致），实测样本里已经一条都不需要顺序表。把它留成引擎能力并这样锁住，
    是因为只要以后分组口径一放宽，它立刻又会被用到。
    """

    库 = {
        "999001": {
            "主体": {"状态": {"属性": {"速度": param("速度"), "攻击": param("攻击")}}},
        }
    }
    引用 = {
        "模板": "999001",
        "参数": {"速度": 12, "攻击": 15},
        "顺序": {"/状态/属性": ["攻击", "速度"]},
    }
    模板模块.expand_in_place(引用, 库)
    assert list(引用["状态"]["属性"]) == ["攻击", "速度"]
    assert 引用["状态"]["属性"] == {"攻击": 15, "速度": 12}
    # 记录的顺序与展开后的键集不一致时**不重排**：那条记录不该管这里。
    其他 = {
        "模板": "999001",
        "参数": {"速度": 12, "攻击": 15},
        "顺序": {"/状态/属性": ["攻击", "格挡率"]},
    }
    模板模块.expand_in_place(其他, 库)
    assert list(其他["状态"]["属性"]) == ["速度", "攻击"]


def test_optional_parameter_absence_is_preserved() -> None:
    """可选参数缺失时，展开结果里也不能有那个键。

    否则会凭空补出字段、与原实例不等价。
    """

    库 = {
        "999002": {
            "主体": {"数值": {"来源": param("来源"), "最高值": param("最高值")}},
        }
    }
    引用 = {
        "模板": "999002",
        "参数": {"来源": "自身攻击", "最高值": 模板模块.OMIT},
    }
    模板模块.expand_in_place(引用, 库)
    assert 引用 == {"数值": {"来源": "自身攻击"}}
    assert "最高值" not in 引用["数值"]


def test_parameter_may_be_keyed_by_name_or_path() -> None:
    """参数键认三种写法：占位符名、键名、位置路径。"""

    主体 = {"效果": [{"状态": {"名称": param("p1")}}]}
    库 = {"999003": {"主体": 主体, "参数位置": {"/效果/[0]/状态/名称": "p1"}}}
    for 键 in ("p1", "名称", "/效果/[0]/状态/名称"):
        引用 = {"模板": "999003", "参数": {键: "苍龙养元"}}
        模板模块.expand_in_place(引用, 库)
        assert 引用 == {"效果": [{"状态": {"名称": "苍龙养元"}}]}, 键


def test_missing_parameter_is_rejected() -> None:
    库 = {"999004": {"主体": {"效果": [{"状态": {"名称": param("p1")}}]}}}
    with pytest.raises(模板模块.TemplateError, match="缺少参数"):
        模板模块.expand_in_place({"模板": "999004", "参数": {}}, 库)


def test_unknown_parameter_position_is_rejected() -> None:
    """实参带了一个主体里不存在的位置：必须报错，绝不静默忽略。

    静默忽略会让展开结果悄悄少一个值，那是最难查的一类坏数据。
    """

    库 = {"999005": {"主体": {"效果": [{"状态": {"名称": param("p1")}}]}}}
    with pytest.raises(模板模块.TemplateError, match="没有参数位置"):
        模板模块.expand_in_place({"模板": "999005", "参数": {"没有这个": 1}}, 库)


def test_unknown_template_is_rejected() -> None:
    with pytest.raises(模板模块.TemplateError, match="不存在"):
        模板模块.expand_in_place({"模板": "999999", "参数": {}}, {})


def test_cyclic_reference_is_rejected() -> None:
    库 = {
        "1": {"主体": {"模板": "2", "参数": {}}},
        "2": {"主体": {"模板": "1", "参数": {}}},
    }
    with pytest.raises(模板模块.TemplateError, match="循环引用"):
        模板模块.expand_in_place({"模板": "1", "参数": {}}, 库)


# ---------------------------------------------------------------- 工具


def _collect_references(node: object) -> list[dict]:
    出: list[dict] = []

    def 走(current: object) -> None:
        if isinstance(current, dict):
            if "模板" in current:
                出.append(current)
                return
            for value in current.values():
                走(value)
        elif isinstance(current, list):
            for item in current:
                走(item)

    走(node)
    return 出


def _placeholder_paths(body: object) -> dict[str, str]:
    out: dict[str, str] = {}

    def 走(node: object, path: str) -> None:
        if isinstance(node, dict):
            if set(node) == {模板模块.PLACEHOLDER_KEY}:
                out[path] = str(node[模板模块.PLACEHOLDER_KEY])
                return
            for key, value in node.items():
                走(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                走(item, f"{path}/[{index}]")

    走(body, "")
    return out


def _first_scalar_path(node: object, path: str = "") -> str | None:
    if isinstance(node, dict):
        if set(node) == {模板模块.PLACEHOLDER_KEY}:
            return None
        for key, value in node.items():
            命中 = _first_scalar_path(value, f"{path}/{key}")
            if 命中:
                return 命中
        return None
    if isinstance(node, list):
        for index, item in enumerate(node):
            命中 = _first_scalar_path(item, f"{path}/[{index}]")
            if 命中:
                return 命中
        return None
    return path


def _set_path(node: object, path: str, value: object) -> None:
    parts = [p for p in path.split("/") if p]
    current = node
    for part in parts[:-1]:
        current = current[int(part[1:-1])] if part.startswith("[") else current[part]
    last = parts[-1]
    if last.startswith("[") and last.endswith("]"):
        current[int(last[1:-1])] = value
    else:
        current[last] = value
