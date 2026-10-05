"""内容寻址的模板库生成器：模板编号 = 主体内容哈希，参数按**位置**作键。

## 与旧生成器的区别

| | 旧 | 新 |
|---|---|---|
| 模板编号 | 按面归一收益排名发的序号 `43NNNN` | 主体内容哈希 `43` + sha256 前 12 位 |
| 参数键 | `p1`/`p2`…（位置首次出现的顺序） | 键名或路径（位置自身的性质） |
| 库与数据的关系 | 数据一变排名全变、引用全失效 | 只新增/删除条目，已有引用不失效 |

## 为什么

旧编号是「排名」，于是**生成库**与**重挂引用**必须严格同步，拆开跑就毁数据（实测
毁出 219 条展不开的引用）；参数按出现顺序编号，删掉一个字段后面全体重编号，同样
让引用失效。内容寻址把这两件事都变成纯函数：编号由主体唯一决定，参数身份由位置
唯一决定。

## 覆盖判据

一个结构簇进库的条件是：**这个簇的全部实例都能由同一份主体无损还原**
（`templates.restore_reference`，即装载期展开后与原文逐字节相同）。

簇结构同质时「一条能过 → 全簇都能过」。非同质的簇（`_stabilize` 那种要一轮轮剔实例
的）在这里**直接不收**：它本来就是在猜，收进去也只会让「同一模板有两种还原结果」
这种说不清的状态进库。这些实例留在数据里当原文，展开时原样输出，不影响正确性。

用法：

    .venv/Scripts/python.exe -X utf8 tools/构筑模板代码化.py --输出 game/core/combat/template_data.py
"""

from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import sys
import tempfile
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
for _path in (str(ROOT), str(TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

模板 = importlib.import_module("构筑模板")
ABILITY = 模板.ABILITY
PLACEHOLDER = "$参数"

from game.core.combat.templates import (  # noqa: E402
    PLACEHOLDER_KEY,
    TEMPLATE_KEY,
    body_digest,
    index_map,
    param,
)

HEADER = '''"""构筑模板库（自动生成，不要手改）。

由 `tools/构筑模板代码化.py` 从**功法 / 真意 / 器律 / 战场环境 / 伤势 / 战丹**六个面的
真实实例机械生成（六面共用一份库；见 `tools/构筑模板.py` 的 `SEGMENTS`）。

## 编号就是内容地址

模板编号是 `模板主体` 的内容哈希（`templates.body_digest`，`43` + sha256 前 12 位），
不是按收益排名发的序号。这样做的好处是**重新生成库永远不会让已有引用失效**：同一份
主体永远得到同一个编号，数据里那条引用只要编号还在库里就照旧成立。旧方案用排名编号，
数据一变就全体重编号，换库与重挂引用必须严格同步，拆开跑就毁数据。

## 参数按位置

引用的参数键是**键名或位置路径**（如 `{"层数": 1}` 或 `{"/效果/[0]/层数": 1}`），
不是 `p1`/`p2` 这种按出现顺序编的号。删掉一个字段不会让别的参数改号。

## 覆盖

每份模板的全部实例都用 `templates.restore_reference` 验过「装载期展开后与原文逐字节
相同」——键序不同时由引用自己的 `顺序` 键兜住。**无法由同一主体无损还原的结构簇不收**，
那些实例留在数据里当原文。

要改模板请改生成器或数据，然后重新生成；直接编辑本文件会在下次生成时被覆盖。
"""

from __future__ import annotations

from typing import Any

from .templates import TemplateLibrary, param


def library() -> TemplateLibrary:
    """返回全部模板：编号 -> {说明, 主体}。

    只有这两个键。参数位置、动作序列、叶子路径表都能从 `主体` 现算，**不在库里另存
    一份**——存了就要永远保持一致，那正是「一句话写两遍」（实测漂移过：219 条引用
    展不开）。唯一不能从主体算出来的是「这份模板产自哪个面」，它单独放在
    `TEMPLATE_FACES` 里。
    """

    return {
'''

FOOTER = '''    }


'''


def _entry(unit: dict) -> tuple | None:
    """把一个结构簇收成一份带哈希编号的模板条目。

    返回 `(编号, 主体, 动作序列, 叶子路径表, 面)`；整簇无法无损还原时返回 None。
    """

    instances = unit["实例"]
    params, _names = 模板._derive_params(instances)
    try:
        template = 模板._build_template(instances, params)
    except KeyError:
        return None

    位置表 = index_map(template)
    占位符 = {path: param(名字) for path, 名字 in 位置表.items()}
    try:
        body = json.loads(json.dumps(template, ensure_ascii=False))
        for path, 节点 in 占位符.items():
            模板._set_leaf(body, path, 节点)
    except (KeyError, IndexError):
        return None

    编号 = body_digest(body)
    库 = {编号: {"主体": body}}
    from game.core.combat import templates as 引擎

    for _cid, effect, _face in instances:
        if 引擎.restore_reference(编号, body, effect, 库) is None:
            return None
    return (
        编号,
        body,
        tuple(模板._ability_sequence(body, [])),
        unit["签名"],
        unit["面"],
    )


def _render(编号: str, 条目: tuple) -> str:
    from game.core.combat.templates import describe

    _编号, body, _序列, _签名, _面 = 条目
    行 = [f'        "{编号}": {{']
    行.append('            "说明": ' + _py_literal(describe(body)) + ",")
    行.append('            "主体": ' + _body_literal(body) + ",")
    行.append("        },")
    return "\n".join(行)


def _py_literal(value: Any) -> str:
    """把 JSON 值渲染成 Python 字面量源码。

    模板主体是**代码化**的（理由见模块开头），所以这里不用 `json.dumps`：JSON 的
    `true/false/null` 在 Python 里不是字面量，渲染出来会直接语法错误。
    """

    if value is None:
        return "None"
    if value is True:
        return "True"
    if value is False:
        return "False"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dict):
        体 = ", ".join(f"{_py_literal(k)}: {_py_literal(v)}" for k, v in value.items())
        return "{" + 体 + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_py_literal(item) for item in value) + "]"
    raise TypeError(f"无法渲染成 Python 字面量：{type(value).__name__}")


def _body_literal(node: Any) -> str:
    """渲染模板主体：`{"$参数": 名字}` 写成 `param("名字")`。

    占位符在库里是**真的函数调用**而不是字面量——这样主体一读就是「这里要填参数」，
    而不是一句冷冰冰的 `{"$参数": "p1"}`。
    """

    if isinstance(node, dict):
        if set(node) == {PLACEHOLDER_KEY}:
            return f"param({json.dumps(str(node[PLACEHOLDER_KEY]), ensure_ascii=False)})"
        体 = ", ".join(
            f"{_py_literal(k)}: {_body_literal(v)}" for k, v in node.items()
        )
        return "{" + 体 + "}"
    if isinstance(node, (list, tuple)):
        return "[" + ", ".join(_body_literal(item) for item in node) + "]"
    return _py_literal(node)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--输出", default="", help="输出路径；默认写临时目录")
    parser.add_argument("--展开", action="store_true",
                        help="先把 data/ 里的引用展开成原文再挖库（数据不是原文形态时必须加）")
    parser.add_argument("--按实例", action="store_true",
                        help="除按形状收簇外，再为每个效果实例各铸一条专属模板（一卡一条）")
    args = parser.parse_args()

    if args.展开:
        _展开成原文()

    单元 = 模板._ranked_units(模板._collect_units())
    if args.按实例:
        实例单元 = []
        for key, bucket in 模板._collect_effects().items():
            for inst in bucket["实例"]:
                实例单元.append({
                    "序列": key,
                    "签名": 模板._shape(inst[1]),
                    "面": inst[2],
                    "实例": [inst],
                })
        print(f"按实例：额外 {len(实例单元)} 个单例单元")
        单元 = 单元 + 实例单元
    print(f"结构簇 {len(单元)} 个")

    条目表: dict[str, tuple] = {}
    跳过 = 0
    跨面合并 = 0
    for unit in 单元:
        条目 = _entry(unit)
        if 条目 is None:
            跳过 += 1
            continue
        编号 = 条目[0]
        if 编号 in 条目表:
            # 同号 = 同主体。不同面（或不同结构簇）算出同一份主体时，一份模板就能
            # 代表它们全部，合并即可——内容是同一份，不存在丢东西。
            跨面合并 += 1
            continue
        条目表[编号] = 条目
    print(f"新库 {len(条目表)} 份模板；未收结构簇 {跳过} 个（整簇无法无损还原）")
    if 跨面合并:
        print(f"  {跨面合并} 个结构簇与已有模板同号（同一份主体、来自不同面），已合并")

    chunks = [HEADER]
    for 编号, 条目 in 条目表.items():
        chunks.append(_render(编号, 条目))
    chunks.append(FOOTER)
    chunks.append("#: 每份模板的**结构签名**：编号 -> (动作序列, 叶子路径表)。")
    chunks.append("#: 迁移用它把一条效果定位到唯一模板：动作序列相同但字段集合不同的实例，")
    chunks.append("#: 落在不同的结构簇里，各自有模板。")
    chunks.append("#: 动作序列与叶子路径表都**能从主体现算**（`templates.describe` / `paths_in`），")
    chunks.append("#: 这里存一份只是为了让迁移 O(1) 查表，不再另存一份「动作序列表」。")
    chunks.append("TEMPLATE_CLUSTERS: dict[str, tuple] = {")
    for 编号, 条目 in 条目表.items():
        chunks.append(
            f'    "{编号}": ({_py_literal(list(条目[2]))}, {_py_literal(list(条目[3]))}),'
        )
    chunks.append("}")
    chunks.append("")
    chunks.append("")
    chunks.append("#: 每份模板**产自哪个面**：编号 -> 面名。")
    chunks.append("#: 面进簇标识——不同面的同名效果必须分开管，否则排名与迁移核对都会错位。")
    chunks.append("#: 它是**唯一**不能从主体算出来的信息（主体里没有「这张卡属于哪个面」）。")
    chunks.append("TEMPLATE_FACES: dict[str, str] = {")
    for 编号, 条目 in 条目表.items():
        chunks.append(f'    "{编号}": {_py_literal(条目[4])},')
    chunks.append("}")
    chunks.append("")
    payload = "\n".join(chunks)

    输出 = pathlib.Path(args.输出) if args.输出 else pathlib.Path(tempfile.gettempdir()) / "template_data.py"
    输出.write_text(payload, encoding="utf-8")
    print(f"已写入 {输出}（{len(payload.splitlines())} 行）")
    return 0


def _展开成原文() -> None:
    """把 `data/` 里的模板引用展开成原文并原地落盘。

    挖库的输入必须是原文：数据一旦被引用化，`_collect_units` 只找得到残片（实测在
    引用形态的仓库上只挖出 87 个簇，而库里有 1,400+ 份模板）。
    """

    from game.core.combat import templates as 引擎
    from game.core.combat.template_data import library

    库 = library()
    for 面, 配置 in 模板.SEGMENTS.items():
        引用 = 0
        for path in sorted(配置["目录"].glob(配置["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            条目表 = 文档 if isinstance(文档, list) else [文档]
            for 实体 in 条目表:
                if isinstance(实体, dict):
                    引用 += json.dumps(实体, ensure_ascii=False).count(f'"{TEMPLATE_KEY}"')
                    引擎.expand_in_place(实体, 库)
            path.write_text(
                json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        print(f"面 {面:<6} 已展开成原文（原有 {引用} 条引用）")


if __name__ == "__main__":
    raise SystemExit(main())
