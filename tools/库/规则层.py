"""工具侧读取战斗规则层登记表。

游戏侧走 `foundation` 启动校验后再交给引擎；工具侧不建服务，直接读同一份数据文件
（与 `检查原子能力.py` 读 `原子能力.json` 同一个口径）。**只有这一处读它**，
免得几个工具各写一份路径。
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
RULE_LAYER_PATH = ROOT / "data" / "战斗" / "定义" / "规则层.json"


def load_rule_layer() -> dict[str, dict]:
    """返回 `规则名 -> 定义`。"""

    return json.loads(RULE_LAYER_PATH.read_text(encoding="utf-8"))


__all__ = ["RULE_LAYER_PATH", "load_rule_layer"]
