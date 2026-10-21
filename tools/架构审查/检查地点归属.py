"""地点归属判据：地点目录里的州，必须就是它坐标所在的州。

为什么要有它：地点按「州/地点」分目录（人看地图有方向），而「这个地点属于哪个州」
真正的答案是坐标落在哪个区域的坐标带里。两者是同一件事的两种表达——
目前 77 个地点全部一致，但没有判据时，改坐标忘了搬目录、或改区域边界忘了搬地点，
都会让两者悄悄分叉，而且谁也发现不了。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查地点归属.py

**退出码：0 = 一致，1 = 有地点放错州目录。**
"""
from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTENT = ROOT / "data" / "世界" / "内容"


def _regions() -> dict[str, set[tuple[int, int]]]:
    regions: dict[str, set[tuple[int, int]]] = {}
    for path in sorted((CONTENT / "区域").glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        cells: set[tuple[int, int]] = set()
        for band in value.get("坐标带") or ():
            if not isinstance(band, dict):
                continue
            y = band.get("y")
            for span in band.get("x轴") or ():
                if isinstance(span, list) and len(span) == 2:
                    for x in range(span[0], span[1] + 1):
                        cells.add((x, y))
        regions[path.stem] = cells
    return regions


def main() -> int:
    regions = _regions()
    problems: list[str] = []
    checked = 0
    for path in sorted((CONTENT / "地点").rglob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        xy = value.get("坐标")
        if not isinstance(xy, list) or len(xy) != 2:
            continue
        point = (xy[0], xy[1])
        directory_region = path.parent.name
        actual = [name for name, cells in regions.items() if point in cells]
        checked += 1
        if not actual:
            problems.append(f"{path.stem}：坐标 {point} 不在任何区域的坐标带里")
            continue
        if directory_region not in actual:
            problems.append(
                f"{path.stem}：放在「{directory_region}」目录，"
                f"但坐标 {point} 落在「{'、'.join(actual)}」"
            )
    if problems:
        print("地点归属不一致：")
        for item in problems:
            print("  " + item)
        print()
        print("要么把地点搬进它坐标所属的州，要么改坐标带让它落在这里。")
        return 1
    print(f"地点归属审查通过：{checked} 个地点，目录与坐标带一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
