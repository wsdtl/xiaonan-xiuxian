"""【已归档，不再是流水线的一部分】从真实实例机械生成「构筑模板」的 JSON 形态原型。

## 为什么归档

这个原型把模板当成 **`data/` 里的编号实体**（含 `编号/名称/参数/主体`）。那个方向
最后没有被采用：模板是**引擎基础设施**，生成一次就该固定，进 `data/` 反而会让人以为
要手工维护；而且每个面的模板都要读一遍 JSON、再校验一遍。

落地的是 `tools/构筑模板代码化.py`：同样从实例机械生成，但**产出 Python 模块**
（`game/core/combat/template_data.py`），校验方式是引擎自己的展开回环
（`templates.restore_reference`）。本文件保留下来只作为那条路线的记录，
**它依赖的 `模板._ranked` 已经不存在**，直接跑会报错。

## 它当初解决什么

模板要进 `data/`，就必须先是**合法的游戏数据**：每个能力节点都要能过
`RuleSchemaValidator`（原子能力、字段、允许执行器、条件必填）。手写一份模板没法保证
这一点，所以这里从**已有实例**生成模板——实例本身是跑得通的合法数据，把它们里
随卡变化的位置换成占位符，得到的就是合法模板。

## 用法

```powershell
# 生成到临时目录并校验（默认，不碰 data/）
.venv/Scripts/python.exe -X utf8 tools/构筑模板生成.py --原型 1

# 生成全部可单模板还原的原型
.venv/Scripts/python.exe -X utf8 tools/构筑模板生成.py --全部

# 写到指定路径
.venv/Scripts/python.exe -X utf8 tools/构筑模板生成.py --原型 1 --输出 <路径>
```

**默认不写进 `data/`。** 模板真正落地要先决定它在 `data/` 里的位置与编号段，
以及引擎怎么在加载期展开（见 `tools/构筑模板化方案.md` 第四节）。
"""

from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

模板 = importlib.import_module("构筑模板")
ABILITY = 模板.ABILITY

#: 模板编号前缀段。功法 40 / 真意 41 / 气机 42 / 器律 70，模板取 43（下一个空位）。
TEMPLATE_PREFIX = "43"


def _build_one(rank: int, groups) -> dict[str, Any]:
    ranked = 模板._ranked(groups)
    key, instances = ranked[rank - 1]
    params, _names = 模板._derive_params(instances)
    body = 模板._build_template(instances, params)

    positions: dict[str, list[str]] = {}
    for path, name in params.items():
        positions.setdefault(name, []).append(path)

    return {
        "编号": f"{TEMPLATE_PREFIX}{rank:04d}",
        "名称": f"构筑模板-{rank}",
        "说明": "由 tools/构筑模板生成.py 从真实实例机械生成；参数位置见 参数 字段。",
        "动作序列": list(key),
        "覆盖实例数": len(instances),
        "参数": {name: sorted(paths) for name, paths in sorted(positions.items())},
        "主体": body,
    }


def _validate(templates: list[dict[str, Any]], groups) -> tuple[bool, str]:
    """证明模板**展开后**是合法游戏数据。

    注意：不能直接校验模板本体——本体里参数位置是 `{"$参数": …}` 占位符，
    像 `左值.状态` 那种位置要求字符串，占位符必然过不了。所以先按一组真实实参展开，
    再校验展开结果。这才对应「模板能不能生成出合法数据」这个真问题。
    """

    sys.path.insert(0, str(ROOT))
    from game.app import build_game_services
    from game.core.combat.foundation import rule_validator
    from game.core.data import materialize

    ranked = 模板._ranked(groups)
    built = build_game_services()
    try:
        validator = rule_validator(materialize(built.core.data.dataset("战斗定义")))
        checked = 0
        for template in templates:
            rank = int(template["编号"][len(TEMPLATE_PREFIX):])
            _key, instances = ranked[rank - 1]
            params, _names = 模板._derive_params(instances)
            # 用第一个实例的实参展开：它代表真实卡片的取值。
            bound = 模板._bind(instances[0][1], params)
            expanded = 模板._expand(template["主体"], bound)
            for index, effect in enumerate(expanded.get("效果") or []):
                validator.validate_node(effect, f"{template['编号']}.展开.效果[{index}]")
                checked += 1
        return True, f"模板展开后校验通过：{len(templates)} 份模板、{checked} 个顶层效果"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        built.core.database.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--原型", type=int, default=1, help="按排名生成单个原型")
    parser.add_argument("--全部", action="store_true", help="生成全部可单模板还原的原型")
    parser.add_argument("--输出", default="", help="输出路径；默认写到临时目录")
    args = parser.parse_args()

    groups = 模板._collect_effects()
    ranked = 模板._ranked(groups)

    if args.全部:
        targets = []
        for rank, (key, instances) in enumerate(ranked, 1):
            params, _ = 模板._derive_params(instances)
            try:
                模板._build_template(instances, params)
            except KeyError:
                continue  # 多形态原型，跳过
            targets.append(rank)
    else:
        targets = [args.原型]

    templates = [_build_one(rank, groups) for rank in targets]
    ok, message = _validate(templates, groups)
    print(message)

    if not ok:
        return 1

    payload = json.dumps(templates, ensure_ascii=False, indent=2) + "\n"
    if args.输出:
        out = pathlib.Path(args.输出)
    else:
        import tempfile

        out = pathlib.Path(tempfile.gettempdir()) / "构筑模板.json"
    out.write_text(payload, encoding="utf-8")
    print(f"已写出 {out}（{len(templates)} 份模板，{len(payload.splitlines())} 行）")
    for template in templates[:5]:
        params = len(template["参数"])
        print(f"  {template['编号']} 覆盖 {template['覆盖实例数']} 个实例、{params} 个参数")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
