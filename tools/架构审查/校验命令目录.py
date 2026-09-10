"""命令目录与 scope 一致性审查。

`game/cmd/说明.md` 规定：每条命令必须在 `metadata` 中声明 `scope` 为
`通用`、`专属` 或 `后台`，且该值必须与实际所在目录一致。本脚本是这条
规则的手动审查入口，不进入游戏启动流程。

用法：

```powershell
.venv/Scripts/python.exe -X utf8 tools/架构审查/校验命令目录.py
```

退出码 0 表示全部一致，1 表示存在越界。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import game.cmd  # noqa: E402  - 导入即按声明注册全部命令组件
from game.cmd.command import registered_commands  # noqa: E402

# 二级命令目录 -> 必须声明的 scope。目录名与 scope 同名，集中登记便于比对。
SCOPE_BY_TOP_DIR = {"通用": "通用", "专属": "专属", "后台": "后台"}


def audit() -> list[str]:
    """返回全部越界描述；空列表表示一致。"""

    problems: list[str] = []
    for command, scope, module in registered_commands():
        parts = module.split(".")
        if len(parts) < 3 or parts[0] != "game" or parts[1] != "cmd":
            continue
        expected = SCOPE_BY_TOP_DIR.get(parts[2])
        if expected is None:
            problems.append(f"{command}：命令组件不在 通用/专属/后台 之下（{module}）")
            continue
        if scope != expected:
            problems.append(
                f"{command}：目录要求 scope={expected}，"
                f"实际声明 {scope or '<空>'}（{module}）"
            )
    return problems


def main() -> int:
    commands = registered_commands()
    problems = audit()
    if not problems:
        print(f"命令目录与 scope 一致性审查通过：{len(commands)} 条命令")
        return 0
    print(f"命令目录与 scope 越界 {len(problems)} 处：")
    for problem in problems:
        print(f"  {problem}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
