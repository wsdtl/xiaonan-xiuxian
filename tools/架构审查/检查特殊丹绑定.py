"""特殊丹绑定审查：特殊丹一律**绑定地点功能**使用，双向都得对得上。

约定（既有做法，不是本轮新定）：

- 绑定写在**世界数据**里：`data/世界/内容/<州>/<地点>/<地点>.json` 的 `功能配置.<功能>.丹药 = <编号>`；
- 该功能还要在 `data/世界/定义/地点功能.json` 里登记（否则装载器直接拒绝启动），
  并在 `data/世界/位置/展示/按钮/地点功能.json` 里给出玩家可见的按钮或命令；
- 机制类型要登记在 `data/物品/基础物品/定义/使用效果.json`；
- 参数（如目标种族、性别取值）写**地点配置**里，不写丹里。

本判据验三件事：

1. 地点配置里指名的 `丹药` 必须真是一枚丹药（编号写错等于地点功能不可用）；
2. 被指名的那种功能必须在两张表里都登记过（否则装载器过不去，这条是提前拦）；
3. 每枚特殊丹的 `使用效果.类型` 必须在契约里；并且**统计**没有被任何地点指名的特殊丹——
   这类丹玩家拿不到入口，属于待收口项（列出来，不静默）。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查特殊丹绑定.py

**退出码：0 = 绑定自洽，1 = 有违规。**
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _pills() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for path in sorted((DATA / "物品" / "炼丹" / "内容" / "丹药" / "特殊丹").glob("*.json")):
        for row in _load(path):
            if isinstance(row, Mapping):
                effect = row.get("使用效果")
                kind = str((effect or {}).get("类型") or "") if isinstance(effect, Mapping) else ""
                out.append((str(row.get("编号")), str(row.get("名称")), kind))
    return out


def _nested_medicine(node: object) -> list[tuple[str, Mapping[str, object]]]:
    """递归找出块里所有的「丹药」声明。

    关键：绑定**不一定在第一层**——铜雀台的夺元把守真定契丹写在 `服丹` 子块里
    （`功能配置.夺元.服丹.丹药`）。我第一版只看第一层，于是把 160003 误报成「未绑定」，
    所以这里必须递归。返回（字段路径, 所在块）。
    """

    out: list[tuple[str, Mapping[str, object]]] = []
    if isinstance(node, Mapping):
        生 = node.get("丹药")
        if isinstance(生, str) and 生:
            out.append(("", node))
        for key, value in node.items():
            for sub_path, block in _nested_medicine(value):
                out.append((f"{key}.{sub_path}" if sub_path else str(key), block))
    elif isinstance(node, list):
        for value in node:
            out.extend(_nested_medicine(value))
    return out


def _bindings() -> list[tuple[str, str, str, Mapping[str, object]]]:
    out: list[tuple[str, str, str, Mapping[str, object]]] = []
    for path in (DATA / "世界" / "内容").rglob("*.json"):
        try:
            body = _load(path)
        except Exception:
            continue
        cfg = body.get("功能配置") if isinstance(body, Mapping) else None
        if not isinstance(cfg, Mapping):
            continue
        for fn, item in cfg.items():
            for sub_path, block in _nested_medicine(item):
                code = block.get("丹药")
                if isinstance(code, str) and code:
                    out.append((path.parent.name, str(fn), str(code), block))
    return out


def check_bindings() -> list[str]:
    problems: list[str] = []
    pills = {code: (name, kind) for code, name, kind in _pills()}
    funcs = {str(c.get("名称")) for c in _load(DATA / "世界" / "定义" / "地点功能.json") if isinstance(c, Mapping)}
    buttons = {str(c.get("功能")) for c in _load(DATA / "世界" / "位置" / "展示" / "按钮" / "地点功能.json") if isinstance(c, Mapping)}
    for place, fn, code, item in _bindings():
        if code not in pills:
            problems.append(f"{place}·{fn}：指名的丹药 {code} 不是一枚丹药")
        if fn not in funcs:
            problems.append(f"{place}·{fn}：功能没有登记在 世界/定义/地点功能.json")
        elif fn not in buttons:
            problems.append(f"{place}·{fn}：功能没有玩家入口（按钮表里没有）")
        for key, value in item.items():
            if key == "目标种族" and str(value) not in {
                str(r.get("种族")) for r in _load(DATA / "角色" / "规则" / "种族" / "种族.json") if isinstance(r, Mapping)
            }:
                problems.append(f"{place}·{fn}：目标种族「{value}」不在种族登记表里")
    return problems


def check_pill_types() -> list[str]:
    declared = {str(c.get("类型")) for c in _load(DATA / "物品" / "基础物品" / "定义" / "使用效果.json") if isinstance(c, Mapping)}
    problems: list[str] = []
    for code, name, kind in _pills():
        if kind and kind not in declared:
            problems.append(f"{code} {name}：使用效果类型「{kind}」没在使用效果契约里")
    return problems


def report_unbound() -> list[str]:
    bound = {code for _place, _fn, code, _item in _bindings()}
    loose = [f"{code} {name}" for code, name, _kind in _pills() if code not in bound]
    if loose:
        print("  [提示] 未被任何地点指名的特殊丹（待收口）：" + "、".join(loose))
    return []


CHECKS = (
    ("地点绑定双向一致", check_bindings),
    ("特殊丹类型都在契约里", check_pill_types),
    ("未被指名的丹列出来", report_unbound),
)


def main() -> int:
    failed = 0
    for label, check in CHECKS:
        problems = check()
        if problems:
            failed += 1
            print(f"  [{len(problems)} 处] {label}")
            for line in problems[:6]:
                print("        " + line)
        else:
            print(f"  [干净] {label}")
    if failed:
        print(f"特殊丹绑定审查失败：{failed} 项")
        return 1
    print("特殊丹绑定审查通过：地点绑定双向一致、类型都在契约里")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
