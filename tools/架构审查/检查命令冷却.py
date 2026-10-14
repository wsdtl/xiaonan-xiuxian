"""命令冷却判据：cooldown 必须是非负数字，且设了值的命令在注册里真带得到冷却键。

两条各挡一类"静默失效"（写错了不炸、只是不生效）：

1. 静态：@GameCommand 装饰器的 cooldown 参数只许写非负数字字面量——布尔、字符串、负数一律报。
   只在装饰器**参数块内**找、并跳过注释行，避免把形参默认值与代码注释误判成字面量。
2. 运行：导入后读本地注册表，凡 metadata 里带 冷却秒 > 0 的，必须同时有合法的
   冷却键（形如 cd-<序号>）与非空 冷却名。这条挡的是"设了却没透传到注册"。

退出码 0 表示干净，1 表示有问题。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launch.adapter.local.handler import LocalEventHandler  # noqa: E402

import game.cmd.command  # noqa: E402,F401 - 导入即触发全部命令注册

DECORATOR = re.compile(r"@GameCommand\.(?:command|fullmatch|regex)\(", re.M)
COOLDOWN_ARGUMENT = re.compile(r"\bcooldown\s*=\s*([^,\s)]+)")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
COOLDOWN_KEY = re.compile(r"^cd-\d+$")

COOLDOWN_SECONDS_FIELD = "冷却秒"
COOLDOWN_KEY_FIELD = "冷却键"
COOLDOWN_NAME_FIELD = "冷却名"


def _argument_problems() -> list[str]:
    """静态：装饰器参数块里的 cooldown 必须是非负数字字面量。"""

    problems: list[str] = []
    for path in (PROJECT_ROOT / "game" / "cmd").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for start in DECORATOR.finditer(text):
            block = text[start.start() : start.start() + 1200]
            cut = block.find("\n)")
            segment = block if cut < 0 else block[:cut]
            for line in segment.splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or "cooldown" not in stripped:
                    continue
                match = COOLDOWN_ARGUMENT.search(stripped)
                if match is None:
                    continue
                value = match.group(1).strip()
                if NUMBER.fullmatch(value):
                    continue
                problems.append(
                    f"{path.relative_to(PROJECT_ROOT)}：cooldown 必须是非负数字字面量，实际写的是 {value!r}"
                )
    return problems


def _registration_problems() -> tuple[list[str], int]:
    """运行：设了冷却的命令，注册条目里必须真带得到冷却键与冷却名。"""

    problems: list[str] = []
    rules = getattr(LocalEventHandler, "command_rules", {}) or {}
    seen = 0
    for command, entries in rules.items():
        for entry in entries:
            metadata = getattr(entry, "metadata", None) or {}
            seconds = metadata.get(COOLDOWN_SECONDS_FIELD)
            if seconds is None:
                continue
            seen += 1
            key = str(metadata.get(COOLDOWN_KEY_FIELD) or "")
            name = str(metadata.get(COOLDOWN_NAME_FIELD) or "")
            if not COOLDOWN_KEY.fullmatch(key):
                problems.append(
                    f"命令「{command}」的冷却键不合法：{key!r}（应为 cd-<序号>）"
                    "—— 多半是设了 cooldown 却没透传到注册"
                )
            if not name:
                problems.append(f"命令「{command}」的冷却名为空（应为首个命令名）")
    return problems, seen


def audit() -> list[str]:
    """返回全部问题描述；空列表表示干净。"""

    problems = _argument_problems()
    registration, seen = _registration_problems()
    problems.extend(registration)
    if not problems:
        print(f"命令冷却判据通过：{seen} 条别名注册带冷却")
    return problems


def main() -> int:
    problems = audit()
    if problems:
        print(f"命令冷却问题 {len(problems)} 处：")
        for problem in problems:
            print(f"  {problem}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())