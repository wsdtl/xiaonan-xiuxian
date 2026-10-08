"""锁定技内容可达性：登记了、也被人带着的规则，在真实内容下必须真的能被触发。

`检查规则层.py` 管的是**登记与实现不脱钩**（字段、条件、名额、拦截点有没有规则用它）；
`验证规则层.py` 用**合成探针**证明引擎机能逐条成立，但它不走 `data/` 里的内容。
于是漏出一类问题：规则齐全、机能也没问题，**可内容永远不会发出这类请求**——规则是死的。
本判据补的就是这一格，模型与 `tools/报告与生成/盘点锁定技.py` 共用 `tools/库/锁定技可达性.py`。

四项检查：

1. **登记规则自带的方向必须可达**：条件里写了具体 `来源关系`（自身/己方/敌方）的，该方向必须在该拦截点的可达集合里；
2. **载体填的方向必须可达**：载体（卡面 `规则文本` / 被动技能行 / 状态定义 / 参战者固有规则）声明的方向必须可达——
   条件里是 `来源关系:$来源` 的规则，方向由载体填，所以这一项才是真正拦住「空转」的那道；
3. **占位符规则必须有人填方向**：`$来源` 的规则，每个载体都要给出 `来源`，否则运行期拿不到参数；
4. **登记但没人带的规则**：只报出来，不判失败（与 `检查规则层.py` 的「卡0/1·族0/1」口径一致）。

口径与边界：拿不准的方向一律算可达，所以报出的违规是**下界**；引擎机能（`rules.INTERCEPTION_POINTS` 的 12 个点）
与合成探针都不动——它们守的是另一件事。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查锁定技可达性.py

**退出码：0 = 全部可达，1 = 有规则在真实内容下触发不了。**
"""

from __future__ import annotations

import pathlib
import sys as _sys

_sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "库"))

import 锁定技可达性 as model

ROOT = pathlib.Path(__file__).resolve().parents[2]


def check_rule_directions() -> list[str]:
    """检查 1：登记规则自带的具体方向必须可达。"""

    got, _ = model.reachable(model.nodes())
    problems: list[str] = []
    for name, row in sorted(model.rules().items()):
        point = str(row.get("拦截点") or "")
        direction = model.rule_direction(row)
        if direction == "不限":
            continue
        if direction not in got.get(point, set()):
            problems.append(
                "%s 的方向是 %s，但 %s 的内容侧发不出这个方向的请求（可达：%s）"
                % (name, direction, point, "/".join(sorted(got.get(point, set()))) or "无")
            )
    return problems


def check_carrier_directions() -> list[str]:
    """检查 2：载体填的方向必须可达。"""

    got, _ = model.reachable(model.nodes())
    layer = model.rules()
    problems: list[str] = []
    for name, used, where in model.carriers():
        row = layer.get(name)
        if row is None:
            problems.append("%s 带的 %s 不在规则层登记表里" % (where, name))
            continue
        point = str(row.get("拦截点") or "")
        direction = model.rule_direction(row, used)
        if direction == "不限":
            continue
        if direction not in got.get(point, set()):
            problems.append(
                "%s 带的 %s（方向 %s）在 %s 上触发不了（可达：%s）"
                % (where, name, direction, point, "/".join(sorted(got.get(point, set()))) or "无")
            )
    return problems


def check_placeholder_supplied() -> list[str]:
    """检查 3：`$来源` 的规则，承载它的每一处都要给出方向。"""

    layer = model.rules()
    problems: list[str] = []
    for name, used, where in model.carriers():
        row = layer.get(name) or {}
        tags = [str(t) for c in (row.get("条件") or []) for t in (c.get("标签") or [])]
        if any("$来源" in tag for tag in tags) and not used:
            problems.append("%s 带的 %s 需要方向，却没写「来源」" % (where, name))
    return problems


def unused_rules() -> list[str]:
    """检查 4：登记了但没有任何载体带着——只报出来。"""

    carrier_names = {name for name, _, _ in model.carriers()}
    return [name for name in sorted(model.rules()) if name not in carrier_names]


CHECKS = (
    ("登记规则方向可达", check_rule_directions),
    ("载体方向可达", check_carrier_directions),
    ("占位符有人填", check_placeholder_supplied),
)


def main() -> int:
    failed = 0
    for label, check in CHECKS:
        problems = check()
        if problems:
            failed += 1
            print("  [%d 处] %s" % (len(problems), label))
            for line in problems[:8]:
                print("        " + line)
            if len(problems) > 8:
                print("        …… 其余 %d 处" % (len(problems) - 8))
        else:
            print("  [干净] %s" % label)
    idle = unused_rules()
    if idle:
        print("  [如实报出] 登记了但没人带的规则 %d 条：%s" % (len(idle), "、".join(idle)))
    if failed:
        print("锁定技可达性审查失败：%d 项" % failed)
        return 1
    print("锁定技可达性审查通过：登记与载体都落在内容发得出来的方向上")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
