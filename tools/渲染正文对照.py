"""渲染正文对照：把渲染器对全部实体的输出做成可比对的摘要。

渲染器是战斗文本的唯一来源（措辞见 `data/战斗/内容/文本规范.md`，实现见
`game/core/combat/card_text.py`），但它此前没有任何入库判据：战斗语料对照只盯战斗
结果，正文多一行、少一行都看不出来。本工具补上这一段——**动渲染器之前先有基准，
动完对照**，差异要为零，或者差异恰好落在你打算改的那批卡上。

用法：

```powershell
.venv/Scripts/python.exe -X utf8 tools/渲染正文对照.py             # 与入库基准对照
.venv/Scripts/python.exe -X utf8 tools/渲染正文对照.py --写基准     # 更新基准
```

摘要只收渲染器现算的正文与未支持项，不收卡片自己的 `说明`：正文必须与 JSON 对齐，
而 `说明` 是人写的风味引言，改它不该让本判据报警。有实体渲染抛错时拒绝写基准，
避免把坏状态固化成判据。

**退出码约定（与另两条语料通道一致）：0 = 一致，1 = 有差异，2 = 有抛错或基准缺失。**
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game.core.combat import render_body, render_listeners  # noqa: E402

DATA = ROOT / "data"
BASELINE = ROOT / "tools/基准/渲染正文摘要.json"

#: 有正文的体裁与它们的文件位置。加一栏就要同时改 `渲染战斗文本.py` 的 SURFACES。
SURFACES = (
    ("功法", "战斗/内容/功法/功法-*.json"),
    ("真意", "战斗/内容/真意/真意-*.json"),
    ("气机", "战斗/内容/气机/气机-*.json"),
    ("器律", "炼器/内容/器律-*.json"),
    ("战场环境", "战斗/内容/战场环境/*.json"),
    ("战丹", "炼丹/内容/丹药/战丹/*.json"),
    ("长期伤势", "角色/内容/伤势.json"),
)


def entries(root: pathlib.Path, pattern: str):
    """按文件顺序产出 (文件, 文件内序号, 实体)。"""

    for path in sorted(root.glob(pattern)):
        document = json.loads(path.read_text(encoding="utf-8"))
        items = document if isinstance(document, list) else [document]
        for index, item in enumerate(items):
            if isinstance(item, dict):
                yield path, index, item


def digest(root: pathlib.Path) -> tuple[dict[str, object], list[str]]:
    """返回（摘要, 渲染失败清单）。

    失败必须记账：渲染器抛错时当成空正文，正好会掩盖最该看见的那类回归。
    """

    summary: dict[str, object] = {}
    failures: list[str] = []
    for section, pattern in SURFACES:
        for path, index, card in entries(root, pattern):
            identity = str(card.get("编号") or card.get("名称") or "")
            key = f"{section}/{identity}"
            if key in summary:
                key = f"{key}#{index}"
            try:
                lines, misses = render_body(card)
                # 长期伤势的规则挂在 `战斗状态.监听` 上，体裁与卡片不同，单独走一条。
                if not lines:
                    state = card.get("战斗状态")
                    if isinstance(state, dict) and state.get("监听"):
                        lines, misses = render_listeners(state)
            except Exception as exc:  # noqa: BLE001 - 任何异常都要变成可见的失败
                failures.append(f"{path.name} {identity}：{type(exc).__name__}: {exc}")
                continue
            summary[key] = {
                "来源": path.relative_to(root).as_posix(),
                "正文": list(lines),
                "未支持": sorted({str(miss) for miss in misses}),
            }
    return summary, failures


def _line_diff(field: str, old: object, new: object) -> list[str]:
    """逐行报差异：只报事实，不改写措辞。"""

    before = old if isinstance(old, list) else []
    after = new if isinstance(new, list) else []
    lines = [f"-{field} {line}" for line in before if line not in after]
    lines.extend(f"+{field} {line}" for line in after if line not in before)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--基准", default=str(BASELINE), help="入库基准摘要")
    parser.add_argument("--写基准", action="store_true", help="把当前摘要写进 --基准")
    parser.add_argument("--数据", default=str(DATA), help="要跑的数据目录")
    args = parser.parse_args()

    root = pathlib.Path(args.数据)
    summary, failures = digest(root)
    print(f"{len(summary)} 条，失败 {len(failures)} 条；数据目录 {root}")
    for failure in failures:
        print(f"  {failure}")

    baseline = pathlib.Path(args.基准)
    if args.写基准:
        if failures:
            print("渲染有失败，拒绝写基准——否则会把坏状态固化成判据。")
            return 2
        baseline.parent.mkdir(parents=True, exist_ok=True)
        # 正文本身很长，摘要用紧凑写法：可读性靠差异输出，不靠这个文件。
        baseline.write_text(
            json.dumps(
                summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"已写入 {baseline}")
        return 0

    if not baseline.is_file():
        print(f"基准不存在：{baseline}；先跑一次 --写基准")
        return 2
    try:
        expected = json.loads(baseline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"基准无法读取：{exc}")
        return 2
    if not isinstance(expected, dict):
        print(f"基准结构不对：{baseline} 应为对象")
        return 2

    changed = sorted(
        key for key in summary.keys() & expected.keys() if summary[key] != expected[key]
    )
    added = sorted(summary.keys() - expected.keys())
    missing = sorted(expected.keys() - summary.keys())
    same = len(summary.keys() & expected.keys()) - len(changed)
    print(
        f"对照 {baseline}（{len(expected)} 条）："
        f"一致 {same} / {len(summary)} · 差异 {len(changed)}"
        f" · 新增 {len(added)} · 缺失 {len(missing)}"
    )
    for key in changed:
        print(f"  [差异] {key}")
        before = expected[key] if isinstance(expected[key], dict) else {}
        after = summary[key] if isinstance(summary[key], dict) else {}
        for field in ("正文", "未支持"):
            for line in _line_diff(field, before.get(field), after.get(field)):
                print(f"      {line}")
    for key in added:
        print(f"  [新增] {key}")
    for key in missing:
        print(f"  [缺失] {key}")
    if failures:
        return 2
    return 1 if (changed or added or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
