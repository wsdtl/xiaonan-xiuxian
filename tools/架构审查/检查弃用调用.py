"""Deprecated symbol guard: the game body must not reference deprecated symbols.

Registry: tools/基准/弃用清单.json -> { "弃用": { "module.symbol": {"替代": ..., "原因": ...} } }
Scan scope: game/**/*.py — imports, attribute access, and bare names.
tools/ and tests/ are allowed to reference deprecated symbols (project convention).

Exit codes: 0 = clean; 1 = deprecated reference found; 2 = registry broken.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "tools/基准/弃用清单.json"
SCAN_ROOT = ROOT / "game"


def load_registry() -> dict[str, dict[str, str]]:
    if not REGISTRY.exists():
        return {}
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entries = data.get("弃用", {})
    if not isinstance(entries, dict):
        raise ValueError("弃用清单的 弃用 字段必须是对象")
    return {str(k): dict(v or {}) for k, v in entries.items()}


def collect_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Import):
            names.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
    return names


def main() -> int:
    try:
        registry = load_registry()
    except Exception as error:  # noqa: BLE001
        print(f"弃用清单读取失败：{error}")
        return 2
    if not registry:
        print("弃用守门：清单为空，待命（0 条弃用登记）")
        return 0
    hits: list[str] = []
    for path in sorted(SCAN_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        names = collect_names(tree)
        for symbol in registry:
            short = symbol.split(".")[-1]
            if symbol in names or short in names:
                hits.append(f"{path.relative_to(ROOT)} 引用了弃用符号 {symbol}")
    print(f"弃用守门：登记 {len(registry)} 条，game/ 违规 {len(hits)} 处")
    for line in hits[:10]:
        print("  [失败] " + line)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
