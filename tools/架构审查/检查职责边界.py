"""职责边界判据：同一个核心状态的写入口必须唯一。

为什么要它：微服务的命名约束放宽以后（视图类组件可以复用别人的服务），
边界只能靠「谁写哪个状态」来守。一个状态被两个核心同时写，出问题时说不清
责任，也会让「谁的规则说了算」变成看代码顺序。

判据只看**常量状态类型**（"StateAddress(user, "xxx", key)"）：非常量的那些
（如道侣的 "companion:<编号>"）留给各自的服务说明去交代，不在这里硬判。

白名单只放**确有必要**的共写：每一条都要写清两个核心各写哪一半。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查职责边界.py

**退出码：0 = 干净，1 = 有未登记的多写者。**
"""
from __future__ import annotations

import ast
import collections
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE = ROOT / "game" / "core"

#: 允许被多个核心共写的状态类型 -> 各写哪一半。
SHARED: dict[str, str] = {}


def _writers() -> dict[str, set[str]]:
    owners: dict[str, set[str]] = collections.defaultdict(set)
    for path in CORE.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        core = path.relative_to(CORE).parts[0]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) < 2:
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else "")
            )
            if name != "StateAddress":
                continue
            arg = node.args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                owners[arg.value].add(core)
    return owners



#: 领域核心 -> 只允许这些前缀的命令组件使用（同域拆分不算重叠）。
#: 跨域共享要登记在 CROSS_DOMAIN，并写清各自用哪一部分。
DOMAIN_CORE = {
    "sect": "zongmen",
    "sect_assets": "zongmen",
    "sect_library": "zongmen",
    "sect_facilities": "zongmen",
    "sect_production": "zongmen",
    "sect_progress": "zongmen",
    "sect_war": "zongmen",
    "duel": "qiecuo",
    "gift": "zengsong",
    "trade": "jiaoyi",
    "raid": "taofa",
    "hosting": "tuoguan",
}

#: 允许跨域共享的核心 -> 理由。
CROSS_DOMAIN = {
    "duel": "zhanbao 只按编号读切磋战报，不发起也不结算",
    "hosting": "chakan_juese 只读托管状态用于人物总览，不认领也不切换",
    "sect": "weizhi 只读宗门同行状态用于附近概览，不写入宗门",
    "sect_war": "zhanbao 只按编号读宗门战报，不发起也不结算",
    "formation": "buzhen 用待战阵法、lianzhen 用炼制预览，各取一面",
    "gathering": "caikuang 与 caiyao 共用同一套采集事实，只是资源类别不同",
    "growth": "daolv_peiyang 与 renwu_peiyang 共用等级曲线，各算各的角色",
    "combat": "chakan_wupin／zhongzu／zhanbao／zhuangpei 只读卡面与规则，不发起战斗",
}


def _feature_cores() -> dict[str, set[str]]:
    tree = ast.parse((ROOT / "game" / "app.py").read_text(encoding="utf-8"))
    core_names = {
        p.name for p in CORE.iterdir() if p.is_dir() and p.name != "__pycache__"
    }
    users: dict[str, set[str]] = collections.defaultdict(set)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        value = node.value
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
            continue
        func = value.func
        fname = func.id if isinstance(func, ast.Name) else ""
        if not fname.endswith("Feature"):
            continue
        names = [a.id for a in value.args if isinstance(a, ast.Name)]
        names += [
            kw.value.id for kw in value.keywords if isinstance(kw.value, ast.Name)
        ]
        for name in names:
            if name in core_names:
                users[name].add(target.id)
    return users


def _domain_problems() -> list[str]:
    users = _feature_cores()
    problems: list[str] = []
    for core, prefix in sorted(DOMAIN_CORE.items()):
        for feature in sorted(users.get(core, ())):
            if feature.startswith(prefix):
                continue
            if core in CROSS_DOMAIN:
                continue
            problems.append(
                f"{core} 只属于 {prefix} 域，却被 {feature} 注入"
            )
    return problems


def main() -> int:
    owners = _writers()
    problems: list[str] = []
    for state_type, cores in sorted(owners.items()):
        if len(cores) < 2:
            continue
        if state_type in SHARED:
            continue
        problems.append(
            f"状态 {state_type} 被多个核心写：{'、'.join(sorted(cores))}"
        )
    problems.extend(_domain_problems())
    if problems:
        print("职责边界问题：")
        for item in problems:
            print("  " + item)
        print()
        print("要么把写入收敛到一个核心，要么在 SHARED 里登记并写清各写哪一半。")
        return 1
    print(
        f"职责边界审查通过：{len(owners)} 个常量状态类型，"
        f"共写登记 {len(SHARED)} 条"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
