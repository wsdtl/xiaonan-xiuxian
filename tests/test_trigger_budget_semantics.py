"""触发预算字段的术语契约：行动不是回合，每次行动不是持有者自己的行动。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OLD = "每次行动最多触发"
NEW = "每次全场主行动最多触发"


def _walk(value):
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            yield node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def test_trigger_budget_field_is_explicitly_global_action() -> None:
    seen = 0
    for path in DATA.rglob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        for node in _walk(document):
            assert OLD not in node, f"{path} 仍在使用旧字段 {OLD}"
            if NEW not in node:
                continue
            if path.name == "原子能力.json":
                assert isinstance(node[NEW], dict), path
                continue
            seen += 1
            assert node.get("能力") == "监听事件", f"{path} 把预算挂在非监听节点上"
            value = node[NEW]
            assert isinstance(value, int) and value >= 0, (path, value)
    assert seen >= 700, seen


def test_trigger_budget_schema_and_docs_use_the_same_words() -> None:
    schema = json.loads((DATA / "战斗/定义/原子能力.json").read_text(encoding="utf-8"))
    text = json.dumps(schema, ensure_ascii=False)
    assert NEW in text
    assert OLD not in text
    docs = (DATA / "战斗/说明.md").read_text(encoding="utf-8")
    assert "按全场主行动" in docs
    assert "不是按某个修士自己的行动" in docs
    assert "引擎没有“回合”" in docs
