"""规则目录不得保存具体地点。

判据来自 `data/基础/读取规则.json:59-63` 的「禁止规则」第一条：
「规则不得保存具体地点、商店或主持者名单」。

**为什么需要这一支**：这条规则此前没有判据在管。2026-10 查处 `data/宗门/规则/山门.json` 时，
它一直存着 `"位置": "宗门园区"` 与 `"位置": "宗门洞天"`——而山门早就改成**按地点功能认**了，
这两个字段是没收掉的残留。删掉后那套真按地点旅行的宗门语料与完整总闸全绿，证明它们确实是死的。

**判据口径（宁可漏、不可猜）**：只在**规则目录**（路径含「规则」且不含「展示」）里，
查键名为 位置 / 地点 / 地点名 / 入口 / 坐标 / 所在 的字段，**且它的值必须正好是一个已知地点名**才算违规。
地点名从 `data/世界/内容/<区域>/<地点>/<地点>.json` 推出（目录名等于文件名的那一层才是地点主体）。
这样「位置: 功法槽」「地点: map」这类同名字段不会被误判。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查规则存地点.py

**退出码：0 = 干净，1 = 有违规。**
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

#: 会装地点的键名。
LOCATION_KEYS = frozenset({"位置", "地点", "地点名", "入口", "坐标", "所在"})
#: 放行名单：(相对路径, 键, 值)。目前为空——真要放行必须在台账里写清理由。
ALLOWED: frozenset[tuple[str, str, str]] = frozenset()


def location_names() -> set[str]:
    """世界内容里「目录名 == 文件名」的那一层才是地点主体，取它的名字。"""
    names: set[str] = set()
    root = DATA / "世界" / "内容"
    if not root.is_dir():
        return names
    for path in root.rglob("*.json"):
        if path.stem == path.parent.name:
            names.add(path.stem)
    return names


def rule_files() -> list[pathlib.Path]:
    """所有规则目录里的 json；展示目录不算（展示本来就要写地点给玩家看）。"""
    out: list[pathlib.Path] = []
    for path in DATA.rglob("*.json"):
        parts = path.relative_to(DATA).parts
        if "展示" in parts or "规则" not in parts:
            continue
        out.append(path)
    return out


def scan_value(rel: str, key: str, value: object, names: set[str], problems: list[str]) -> None:
    """递归整份 json：字典要**全下**，只在「当前键是地点键且值正好是地点名」时才记。

    第一版只递归进「键名是地点键」的分支，于是 `进入` / `离开` 这类外层键把里面的 `位置` 挡住了，
    负向测试（把 `"位置": "宗门园区"` 放回去）当场发现它不红——判据自己漏判。
    """
    if isinstance(value, str):
        if key in LOCATION_KEYS and value in names and (rel, key, value) not in ALLOWED:
            problems.append(f"{rel} 的「{key}」存了具体地点：{value}")
    elif isinstance(value, list):
        for item in value:
            scan_value(rel, key, item, names, problems)
    elif isinstance(value, dict):
        for sub, item in value.items():
            scan_value(rel, sub, item, names, problems)


def find_violations() -> list[str]:
    names = location_names()
    problems: list[str] = []
    for path in rule_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        rel = path.relative_to(ROOT).as_posix()
        scan_value(rel, "", data, names, problems)
    return problems


def main() -> int:
    problems = find_violations()
    if problems:
        for item in problems:
            print(f"   {item}")
        print(f"规则存地点 {len(problems)} 处有问题")
        return 1
    print("规则存地点 干净")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
